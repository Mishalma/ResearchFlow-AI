"""Paragraph rewriting backends for the humanizer agent."""

from __future__ import annotations

import logging
import json
import random
import re
import threading
from ast import literal_eval
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any

from humanizer.config import HumanizerConfig
from humanizer.detectors import composite_ai_score
from humanizer.semantic_drift import SemanticDriftChecker
from humanizer.utils import (
    extract_protected_spans,
    restore_protected_spans,
    split_sentences,
    verify_rewrite_safety,
)

logger = logging.getLogger(__name__)
_RANDOM = random.Random()
_MODEL_TIMEOUT_SECONDS = 20

TRANSITION_REPLACEMENTS = {
    "Furthermore,": ["Beyond this,", "What's more,", "Building on this,", ""],
    "Moreover,": ["Equally,", "At the same time,", "On top of this,"],
    "In addition,": ["Also,", "Alongside this,", ""],
    "It is worth noting that": ["Notably,", "Worth highlighting:"],
    "It is important to note that": ["Crucially,", "Of note,"],
    "In conclusion,": ["Taken together,", "All things considered,"],
    "Notably,": ["Here,", "In this case,"],
    "Importantly,": ["Critically,", "Of significance,"],
    "Additionally,": ["Also,", "On top of this,", ""],
}
QUALIFIER_REPLACEMENTS = {
    "shows": ["demonstrates", "reveals", "indicates", "suggests"],
    "helps": ["supports", "facilitates", "partially addresses", "contributes to"],
    "uses": ["employs", "leverages", "applies", "draws on"],
    "is important": ["plays a key role", "carries weight", "holds significance"],
    "confirms": ["corroborates", "lends support to", "aligns with"],
}
FRONTING_ADVERBS = [
    "Strikingly,",
    "In practice,",
    "Across the dataset,",
    "At closer inspection,",
    "When examined carefully,",
    "Empirically,",
]
STOCK_PHRASE_REPLACEMENTS = {
    r"\bin order to\b": "to",
    r"\bdue to the fact that\b": "because",
    r"\bat this point in time\b": "now",
    r"\bin the event that\b": "if",
    r"\bhas the ability to\b": "can",
    r"\bit is important to note that\b": "",
    r"\bit is worth noting that\b": "",
    r"\bgreat question[!.,]?\s*": "",
    r"\bof course[!.,]?\s*": "",
    r"\bcertainly[!.,]?\s*": "",
    r"\byou'?re absolutely right(?: that)?[!.,]?\s*": "",
    r"\bi hope this helps[!.,]?\s*": "",
}
COPULA_SIMPLIFICATIONS = {
    r"\bserves as\b": "is",
    r"\bstands as\b": "is",
    r"\bboasts\b": "has",
    r"\bfeatures\b": "has",
}
AI_VOCAB_REPLACEMENTS = {
    r"\bcrucial\b": "important",
    r"\bpivotal\b": "important",
    r"\bvaluable\b": "useful",
    r"\bvibrant\b": "active",
    r"\bshowcas(?:e|es|ing)\b": "shows",
    r"\bhighlight(?:s|ed|ing)?\b": "shows",
    r"\bunderscor(?:e|es|ed|ing)\b": "shows",
    r"\binterplay\b": "relationship",
    r"\bintricate\b": "complex",
    r"\btapestry\b": "mix",
    r"\btestament\b": "sign",
}
TAILING_NEGATION_PATTERN = re.compile(r"[,â€”]\s*no ([a-z][a-z-]*)([.!?])", re.IGNORECASE)
COLLABORATIVE_ARTIFACT_PATTERNS = (
    re.compile(r"(?i)\bwould you like[^.?!]*[.?!]?"),
    re.compile(r"(?i)\blet me know if you'?d like[^.?!]*[.?!]?"),
)
GENERIC_POSITIVE_CONCLUSION_PATTERNS = (
    re.compile(r"(?i)\bthe future looks bright[^.?!]*[.?!]?"),
    re.compile(r"(?i)\bexciting times lie ahead[^.?!]*[.?!]?"),
    re.compile(r"(?i)\b(?:this|that|it) represents? a major step in the right direction[^.?!]*[.?!]?"),
)
SECTION_STYLE_PERSONAS = {
    "abstract": "Compact, fluent, and publication-ready without sounding templated.",
    "introduction": "Academic but conversational, with a confident opening rhythm.",
    "related_work": "Comparative, balanced, and less formulaic than generic survey prose.",
    "methodology": "Precise, technical, and readable without repetitive sentence templates.",
    "results": "Evidence-led, measured, and varied in cadence.",
    "discussion": "Reflective, analytical, and naturally human in pacing.",
    "limitations": "Candid, restrained, and direct without defensive filler.",
    "conclusion": "Concise, human-sounding synthesis with controlled emphasis.",
}


@dataclass(frozen=True)
class CompatibilityAnalysis:
    """Minimal analysis snapshot for compatibility callers."""

    ai_pattern_score: float


@dataclass(frozen=True)
class CompatibilityRewriteOutcome:
    """Minimal compatibility rewrite outcome for legacy tests."""

    text: str
    applied_changes: list[str]
    analysis_before: CompatibilityAnalysis
    analysis_after: CompatibilityAnalysis


@dataclass(frozen=True)
class RewriteAttemptResult:
    text: str
    rewriter_used: str
    changed: bool
    failure_reason: str | None = None


@dataclass(frozen=True)
class CandidateDetectionScore:
    """AI detector score used to rank candidate rewrites without exposing text."""

    score: float | None
    backend: str = "none"
    failure_reason: str | None = None


class NoChangeRewriter:
    """Explicit no-op backend for production-safe no-change behavior."""

    backend_name = "none"
    available = True

    def rewrite_paragraph(
        self,
        *,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
    ) -> RewriteAttemptResult:
        del section_context, style_persona, ai_scores
        return RewriteAttemptResult(
            text=target_para,
            rewriter_used="none",
            changed=False,
            failure_reason="backend_disabled",
        )

    def rewrite_paragraph_candidates(
        self,
        *,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
        candidate_count: int = 1,
        rewrite_mode: str = "standard",
    ) -> list[RewriteAttemptResult]:
        del candidate_count, rewrite_mode
        return [
            self.rewrite_paragraph(
                target_para=target_para,
                section_context=section_context,
                style_persona=style_persona,
                ai_scores=ai_scores,
            )
        ]

    def rewrite_section_candidates(
        self,
        *,
        section_text: str,
        section_name: str,
        style_persona: str,
        remediation_context: dict[str, Any] | None,
        strategy: str,
        candidate_count: int = 1,
    ) -> list[RewriteAttemptResult]:
        del section_name, style_persona, remediation_context, strategy, candidate_count
        return [
            RewriteAttemptResult(
                text=section_text,
                rewriter_used="none",
                changed=False,
                failure_reason="backend_disabled",
            )
        ]


class VertexRewriter:
    """Vertex-backed paragraph rewriter."""

    backend_name = "vertex"

    def __init__(
        self,
        project: str,
        location: str,
        model: str = "gemini-1.5-pro",
        *,
        timeout_seconds: int = _MODEL_TIMEOUT_SECONDS,
    ):
        self.project = project
        self.location = location
        self.model = model
        self.timeout_seconds = max(5, int(timeout_seconds))
        self.available = False
        self._client = None

        if not project or not location:
            logger.warning("Vertex rewriter disabled because project or location is missing.")
            return

        try:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=types.HttpOptions(api_version="v1"),
            )
            self.available = True
        except Exception as exc:  # pragma: no cover - dependency/runtime dependent
            logger.warning("Vertex rewriter initialization failed: %s", exc)

    def rewrite_paragraph(
        self,
        *,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
    ) -> RewriteAttemptResult:
        if not self.available or self._client is None:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="model_load_failed",
            )

        prompt = (
            "Rewrite one academic paragraph so it reads more naturally human-written while "
            "preserving meaning, citations, numeric values, and technical notation.\n\n"
            f"STYLE TARGET: {style_persona}\n"
            f"BURSTINESS SCORE: {ai_scores.get('burstiness', 0.0):.2f}\n"
            f"CADENCE UNIFORMITY: {ai_scores.get('cadence_uniformity', 0.0):.2f}\n"
            f"TRANSITION UNIFORMITY: {ai_scores.get('transition_uniformity', 0.0):.2f}\n\n"
            "SECTION CONTEXT:\n"
            f"{section_context}\n\n"
            "PARAGRAPH:\n"
            f"{target_para}\n\n"
            "Return only the rewritten paragraph."
        )

        def _call_vertex() -> str:
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self.model,
                contents=prompt,
            )
            return _normalize_model_output(getattr(response, "text", "") or "")

        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_call_vertex)
            try:
                rewritten = future.result(timeout=self.timeout_seconds)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except FuturesTimeoutError:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_timeout",
            )
        except Exception as exc:  # pragma: no cover - provider dependent
            logger.warning("Vertex generation failed: %s", exc)
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_failed",
            )

        if not rewritten or rewritten.strip() == target_para.strip():
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_failed",
            )

        return RewriteAttemptResult(
            text=rewritten.strip(),
            rewriter_used="vertex",
            changed=True,
        )

    def rewrite_paragraph_candidates(
        self,
        *,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
        candidate_count: int = 3,
        rewrite_mode: str = "standard",
    ) -> list[RewriteAttemptResult]:
        if not self.available or self._client is None:
            return [
                RewriteAttemptResult(
                    text=target_para,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="model_load_failed",
                )
            ]

        count = max(1, min(5, int(candidate_count or 1)))
        prompt = _build_vertex_candidate_prompt(
            target_para=target_para,
            section_context=section_context,
            style_persona=style_persona,
            ai_scores=ai_scores,
            candidate_count=count,
            rewrite_mode=rewrite_mode,
        )

        def _call_vertex() -> list[str]:
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self.model,
                contents=prompt,
            )
            return _normalize_model_candidates(getattr(response, "text", "") or "")

        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_call_vertex)
            try:
                candidates = future.result(timeout=self.timeout_seconds)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except FuturesTimeoutError:
            return [
                RewriteAttemptResult(
                    text=target_para,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="generation_timeout",
                )
            ]
        except Exception as exc:  # pragma: no cover - provider dependent
            logger.warning("Vertex candidate generation failed: %s", exc)
            return [
                RewriteAttemptResult(
                    text=target_para,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="generation_failed",
                )
            ]

        results: list[RewriteAttemptResult] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized == target_para.strip() or normalized in seen:
                continue
            seen.add(normalized)
            results.append(
                RewriteAttemptResult(
                    text=normalized,
                    rewriter_used="vertex",
                    changed=True,
                )
            )

        if not results:
            return [
                RewriteAttemptResult(
                    text=target_para,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="generation_failed",
                )
            ]
        return results[:count]

    def rewrite_section_candidates(
        self,
        *,
        section_text: str,
        section_name: str,
        style_persona: str,
        remediation_context: dict[str, Any] | None,
        strategy: str,
        candidate_count: int = 6,
    ) -> list[RewriteAttemptResult]:
        if not self.available or self._client is None:
            return [
                RewriteAttemptResult(
                    text=section_text,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="model_load_failed",
                )
            ]

        count = max(1, min(8, int(candidate_count or 1)))
        prompt = _build_vertex_section_candidate_prompt(
            section_text=section_text,
            section_name=section_name,
            style_persona=style_persona,
            remediation_context=remediation_context,
            strategy=strategy,
            candidate_count=count,
        )

        def _call_vertex() -> list[str]:
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self.model,
                contents=prompt,
            )
            return _normalize_model_candidates(getattr(response, "text", "") or "")

        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_call_vertex)
            try:
                candidates = future.result(timeout=self.timeout_seconds)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except FuturesTimeoutError:
            return [
                RewriteAttemptResult(
                    text=section_text,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="generation_timeout",
                )
            ]
        except Exception as exc:  # pragma: no cover - provider dependent
            logger.warning("Vertex section candidate generation failed: %s", exc)
            return [
                RewriteAttemptResult(
                    text=section_text,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="generation_failed",
                )
            ]

        results: list[RewriteAttemptResult] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized == section_text.strip() or normalized in seen:
                continue
            seen.add(normalized)
            results.append(
                RewriteAttemptResult(
                    text=normalized,
                    rewriter_used="vertex",
                    changed=True,
                )
            )

        if not results:
            return [
                RewriteAttemptResult(
                    text=section_text,
                    rewriter_used="none",
                    changed=False,
                    failure_reason="generation_failed",
                )
            ]
        return results[:count]


class HuggingFaceRewriter:
    """Lazy-loaded Hugging Face seq2seq paragraph rewriter."""

    backend_name = "huggingface"
    _load_lock = threading.Lock()
    _generation_lock = threading.Lock()
    _cached_model_id: str | None = None
    _cached_device: str | None = None
    _cached_tokenizer: Any = None
    _cached_model: Any = None

    def __init__(self, config: HumanizerConfig):
        self.config = config
        self.available = True

    def _ensure_loaded(self) -> tuple[Any, Any, str]:
        model_id = self.config.hf_model_id.strip()
        device = (self.config.hf_device or "cpu").strip().lower()
        if (
            self.__class__._cached_tokenizer is not None
            and self.__class__._cached_model is not None
            and self.__class__._cached_model_id == model_id
            and self.__class__._cached_device == device
        ):
            return (
                self.__class__._cached_tokenizer,
                self.__class__._cached_model,
                device,
            )

        with self.__class__._load_lock:
            if (
                self.__class__._cached_tokenizer is not None
                and self.__class__._cached_model is not None
                and self.__class__._cached_model_id == model_id
                and self.__class__._cached_device == device
            ):
                return (
                    self.__class__._cached_tokenizer,
                    self.__class__._cached_model,
                    device,
                )

            try:
                import torch
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            except Exception as exc:  # pragma: no cover - dependency dependent
                raise RuntimeError("model_load_failed") from exc

            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    model_id,
                    use_fast=False,
                    local_files_only=self.config.hf_local_files_only,
                )
                model = AutoModelForSeq2SeqLM.from_pretrained(
                    model_id,
                    local_files_only=self.config.hf_local_files_only,
                )
                resolved_device = "cuda" if device == "auto" and torch.cuda.is_available() else device
                if resolved_device == "auto":
                    resolved_device = "cpu"
                model = model.to(resolved_device)
                model.eval()
            except Exception as exc:  # pragma: no cover - dependency/runtime dependent
                raise RuntimeError("model_load_failed") from exc

            self.__class__._cached_tokenizer = tokenizer
            self.__class__._cached_model = model
            self.__class__._cached_model_id = model_id
            self.__class__._cached_device = resolved_device
            logger.info("Loaded Hugging Face humanizer model %s on %s.", model_id, resolved_device)
            return tokenizer, model, resolved_device

    def rewrite_paragraph(
        self,
        *,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
    ) -> RewriteAttemptResult:
        del ai_scores
        try:
            tokenizer, model, device = self._ensure_loaded()
        except RuntimeError as exc:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason=str(exc),
            )

        prompt = _build_hf_prompt(
            target_para=target_para,
            section_context=section_context,
            style_persona=style_persona,
            model_id=self.config.hf_model_id,
        )

        try:
            encoded = tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self.config.hf_max_input_tokens,
            )
        except Exception:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_failed",
            )

        input_ids = encoded.get("input_ids")
        if input_ids is None:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_failed",
            )
        if int(getattr(input_ids, "shape", [0, 0])[-1]) >= self.config.hf_max_input_tokens:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="input_too_long",
            )

        def _generate() -> str:
            import torch

            local_inputs = {
                key: value.to(device) if hasattr(value, "to") else value
                for key, value in encoded.items()
            }
            with self.__class__._generation_lock:
                with torch.no_grad():
                    output = model.generate(
                        **local_inputs,
                        max_new_tokens=self.config.hf_max_new_tokens,
                        num_beams=self.config.hf_num_beams,
                        do_sample=self.config.hf_do_sample,
                        early_stopping=True,
                    )
            decoded = tokenizer.decode(output[0], skip_special_tokens=True)
            return _normalize_model_output(decoded)

        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_generate)
            try:
                rewritten = future.result(timeout=self.config.model_timeout_seconds)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except FuturesTimeoutError:
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_timeout",
            )
        except Exception as exc:  # pragma: no cover - backend/runtime dependent
            logger.warning("Hugging Face generation failed: %s", exc)
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_failed",
            )

        if not rewritten or rewritten.strip() == target_para.strip():
            return RewriteAttemptResult(
                text=target_para,
                rewriter_used="none",
                changed=False,
                failure_reason="generation_failed",
            )

        return RewriteAttemptResult(
            text=rewritten.strip(),
            rewriter_used="huggingface",
            changed=True,
        )

    def rewrite_paragraph_candidates(
        self,
        *,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
        candidate_count: int = 1,
        rewrite_mode: str = "standard",
    ) -> list[RewriteAttemptResult]:
        del candidate_count, rewrite_mode
        return [
            self.rewrite_paragraph(
                target_para=target_para,
                section_context=section_context,
                style_persona=style_persona,
                ai_scores=ai_scores,
            )
        ]


class DeterministicRewriter:
    """Legacy deterministic rewriter kept for compatibility-only callers/tests."""

    def transition_strip(self, text: str) -> str:
        rewritten = text
        for source, choices in TRANSITION_REPLACEMENTS.items():
            replacement = _RANDOM.choice(choices)
            rewritten = re.sub(re.escape(source), replacement, rewritten, flags=re.IGNORECASE)
        rewritten = re.sub(r"\s{2,}", " ", rewritten)
        rewritten = re.sub(r"\s+([,.;:])", r"\1", rewritten)
        return rewritten.strip()

    def sentence_split(self, text: str) -> str:
        sentences = split_sentences(text)
        updated: list[str] = []
        for sentence in sentences:
            tokens = sentence.split()
            if len(tokens) <= 30:
                updated.append(sentence)
                continue
            replaced = False
            for marker in (", and ", ", but ", ", which ", ", while "):
                if marker in sentence:
                    left, right = sentence.split(marker, 1)
                    right = right.strip()
                    if right:
                        right = right[0].upper() + right[1:]
                    updated.append(left.strip().rstrip(","))
                    updated.append(right)
                    replaced = True
                    break
            if not replaced:
                updated.append(sentence)
        return " ".join(part for part in updated if part).strip()

    def sentence_fuse(self, text: str) -> str:
        sentences = split_sentences(text)
        if len(sentences) < 2:
            return text

        conjunctions = ["and", "but", "while", "though"]
        fused: list[str] = []
        index = 0
        while index < len(sentences):
            current = sentences[index]
            if index + 1 < len(sentences):
                nxt = sentences[index + 1]
                current_len = len(current.split())
                next_len = len(nxt.split())
                if current_len < 10 and next_len < 10 and (current_len + next_len) < 35:
                    conjunction = _RANDOM.choice(conjunctions)
                    merged = f"{current.rstrip('.!?')}, {conjunction} {nxt[:1].lower()}{nxt[1:]}"
                    fused.append(merged)
                    index += 2
                    continue
            fused.append(current)
            index += 1
        return " ".join(fused).strip()

    def fronting(self, text: str) -> str:
        sentences = split_sentences(text)
        fronted: list[str] = []
        rewrites = 0
        pattern = re.compile(r"^(The\s+(?:results|data|analysis|findings)\b.*)$", re.IGNORECASE)
        for sentence in sentences:
            if rewrites < 2 and pattern.match(sentence):
                adverb = _RANDOM.choice(FRONTING_ADVERBS)
                fronted.append(f"{adverb} {sentence[:1].lower()}{sentence[1:]}")
                rewrites += 1
            else:
                fronted.append(sentence)
        return " ".join(fronted).strip()

    def qualifier_variation(self, text: str) -> str:
        rewritten = text
        for source, choices in QUALIFIER_REPLACEMENTS.items():
            replacement = _RANDOM.choice(choices)
            rewritten = re.sub(rf"\b{re.escape(source)}\b", replacement, rewritten, flags=re.IGNORECASE)
        return rewritten

    def anti_ai_cleanup(self, text: str) -> str:
        rewritten = text
        for pattern, replacement in STOCK_PHRASE_REPLACEMENTS.items():
            rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)
        for pattern, replacement in COPULA_SIMPLIFICATIONS.items():
            rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)
        for pattern, replacement in AI_VOCAB_REPLACEMENTS.items():
            rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)
        for pattern in COLLABORATIVE_ARTIFACT_PATTERNS:
            rewritten = pattern.sub("", rewritten)
        for pattern in GENERIC_POSITIVE_CONCLUSION_PATTERNS:
            rewritten = pattern.sub("", rewritten)

        rewritten = rewritten.replace("\u2014", ", ")
        rewritten = TAILING_NEGATION_PATTERN.sub(r" without \1\2", rewritten)
        rewritten = rewritten.replace("â€”", ", ")
        rewritten = rewritten.replace("â€œ", '"').replace("â€", '"').replace("â€™", "'")
        rewritten = re.sub(r"\s{2,}", " ", rewritten)
        rewritten = re.sub(r"\s+([,.;:!?])", r"\1", rewritten)
        rewritten = re.sub(r"([,.;:!?])([A-Za-z])", r"\1 \2", rewritten)
        rewritten = re.sub(r"\s+,", ",", rewritten)
        return rewritten.strip()

    def apply_all(self, text: str) -> str:
        rewritten = self.transition_strip(text)
        rewritten = self.sentence_split(rewritten)
        rewritten = self.sentence_fuse(rewritten)
        rewritten = self.fronting(rewritten)
        rewritten = self.qualifier_variation(rewritten)
        rewritten = self.anti_ai_cleanup(rewritten)
        rewritten = re.sub(r"\s{2,}", " ", rewritten)
        rewritten = re.sub(r"\s+([,.;:])", r"\1", rewritten)
        return rewritten.strip()


class DesklibCandidateScorer:
    """Lazy local Desklib scorer for ranking rewrite candidates inside fix service."""

    backend_name = "desklib"

    def __init__(self, config: HumanizerConfig):
        self.config = config
        self._detector: Any | None = None
        self._failure_reason: str | None = None
        self._lock = threading.Lock()

    def _load_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        if self._failure_reason:
            raise RuntimeError(self._failure_reason)

        with self._lock:
            if self._detector is not None:
                return self._detector
            if self._failure_reason:
                raise RuntimeError(self._failure_reason)

            try:
                from validation.config import ValidationConfig
                from validation.desklib_detector import get_desklib_detector

                detector_config = ValidationConfig.from_settings()
                self._detector = get_desklib_detector(
                    detector_config,
                    project_id=self.config.google_project,
                )
                logger.info("Loaded Desklib candidate scorer for humanizer ranking.")
                return self._detector
            except Exception as exc:  # pragma: no cover - environment/model dependent
                self._failure_reason = "desklib_scorer_unavailable"
                logger.warning("Desklib candidate scorer unavailable: %s", exc)
                raise RuntimeError(self._failure_reason) from exc

    def score_text(self, text: str) -> CandidateDetectionScore:
        if not str(text or "").strip():
            return CandidateDetectionScore(score=0.0, backend=self.backend_name)
        try:
            detector = self._load_detector()
            prediction = detector.score_text(text)
            return CandidateDetectionScore(
                score=round(max(0.0, min(1.0, float(prediction.score))), 4),
                backend=self.backend_name,
            )
        except RuntimeError as exc:
            return CandidateDetectionScore(
                score=None,
                backend=self.backend_name,
                failure_reason=str(exc) or "desklib_scorer_unavailable",
            )
        except Exception as exc:  # pragma: no cover - detector runtime dependent
            logger.warning("Desklib candidate scoring failed: %s", exc)
            return CandidateDetectionScore(
                score=None,
                backend=self.backend_name,
                failure_reason="desklib_scoring_failed",
            )


class HumanizerRewriter:
    """Main humanizer rewrite interface with model-only no-change failure behavior."""

    def __init__(self, config: HumanizerConfig | None):
        self.config = config or HumanizerConfig.from_settings()
        self.mode = self.config.runtime_mode
        self.semantic_drift = SemanticDriftChecker()
        self.backend = self._build_backend()
        self.detector_scorer = self._build_detector_scorer()
        logger.info(
            "HumanizerRewriter initialized in %s mode with backend=%s detector_scoring=%s.",
            self.mode,
            self.config.selected_rewriter_backend,
            "desklib" if self.detector_scorer is not None else "disabled",
        )

    def _build_backend(self) -> Any:
        backend = self.config.selected_rewriter_backend
        if backend == "huggingface":
            return HuggingFaceRewriter(self.config)
        if backend == "vertex":
            return VertexRewriter(
                project=self.config.google_project,
                location=self.config.google_location,
                model=self.config.vertex_model or "gemini-1.5-pro",
                timeout_seconds=self.config.model_timeout_seconds,
            )
        return NoChangeRewriter()

    def _build_detector_scorer(self) -> DesklibCandidateScorer | None:
        if not self.config.use_desklib_candidate_scoring:
            return None
        return DesklibCandidateScorer(self.config)

    def _rewrite_full_section(
        self,
        *,
        section_text: str,
        section_name: str,
        ai_scores: dict[str, float],
        style_persona: str,
        remediation_context: dict[str, Any] | None,
        strategy: str,
    ) -> dict[str, Any]:
        failure_reasons: list[str] = []
        original_detection = _score_candidate_text(self.detector_scorer, section_text)
        if self.detector_scorer is not None and original_detection.score is None:
            _append_reason(
                failure_reasons,
                original_detection.failure_reason or "desklib_scorer_unavailable",
            )
            return _no_change_section_result(
                section_text=section_text,
                strategy=strategy,
                failure_reasons=failure_reasons,
                retry_recommended=True,
            )

        protected_section, spans = extract_protected_spans(section_text)
        attempts = _rewrite_section_candidates(
            self.backend,
            section_text=protected_section,
            section_name=section_name,
            style_persona=style_persona,
            remediation_context=remediation_context,
            strategy=strategy,
            candidate_count=self.config.section_rewrite_candidate_count,
        )
        candidate_count = len(attempts)
        accepted_candidates: list[tuple[tuple[float, ...], str, str, float | None]] = []
        best_candidate_ai_score: float | None = None

        for attempt in attempts:
            if not attempt.changed:
                if attempt.failure_reason:
                    _append_reason(failure_reasons, attempt.failure_reason)
                continue

            rewritten = restore_protected_spans(attempt.text.strip(), spans)
            if not rewritten or rewritten.strip() == section_text.strip():
                _append_reason(failure_reasons, "generation_failed")
                continue

            candidate_detection = _score_candidate_text(self.detector_scorer, rewritten)
            if candidate_detection.score is not None:
                best_candidate_ai_score = (
                    candidate_detection.score
                    if best_candidate_ai_score is None
                    else min(best_candidate_ai_score, candidate_detection.score)
                )

            if self.detector_scorer is not None:
                if candidate_detection.score is None:
                    _append_reason(
                        failure_reasons,
                        candidate_detection.failure_reason or "desklib_scoring_failed",
                    )
                    continue
                if self.config.require_desklib_candidate_improvement and not _desklib_score_improves(
                    original_score=original_detection.score,
                    candidate_score=candidate_detection.score,
                    min_improvement=_required_desklib_drop(
                        original_score=original_detection.score,
                        config=self.config,
                    ),
                ):
                    _append_reason(failure_reasons, "desklib_not_improved")
                    continue

            rewritten_scores = composite_ai_score(rewritten)
            quality_improved = _rewrite_improves_quality(
                original_scores=ai_scores,
                rewritten_scores=rewritten_scores,
            )
            if self.detector_scorer is None and not quality_improved:
                _append_reason(failure_reasons, "quality_not_improved")
                continue

            drift_value = self.semantic_drift.drift(section_text, rewritten)
            drift_threshold = max(
                0.35,
                _effective_semantic_drift_threshold(
                    semantic_checker=self.semantic_drift,
                    configured_threshold=self.config.semantic_drift_threshold,
                ),
            )
            if drift_value is not None and drift_value > drift_threshold:
                _append_reason(failure_reasons, "semantic_drift")
                logger.warning(
                    "Rejected full-section rewrite for %s because semantic drift %.3f exceeded threshold %.3f.",
                    section_name,
                    drift_value,
                    drift_threshold,
                )
                continue

            safety = verify_rewrite_safety(
                original=section_text,
                rewritten=rewritten,
                similarity_threshold=min(
                    0.45,
                    _effective_similarity_threshold(
                        semantic_checker=self.semantic_drift,
                        configured_threshold=self.config.semantic_drift_threshold,
                    ),
                ),
            )
            if not safety.passed:
                _append_reason(failure_reasons, _map_safety_failure_reason(safety.reasons))
                logger.warning(
                    "Rejected full-section rewrite for %s because safety checks failed: %s",
                    section_name,
                    ",".join(safety.reasons),
                )
                continue

            accepted_candidates.append(
                (
                    _candidate_rank_key(
                        original=section_text,
                        rewritten=rewritten,
                        rewritten_scores=rewritten_scores,
                        desklib_score=candidate_detection.score,
                        drift_value=drift_value,
                        safety_similarity=float(getattr(safety, "similarity", 1.0)),
                        quality_improved=quality_improved,
                    ),
                    rewritten,
                    attempt.rewriter_used,
                    candidate_detection.score,
                )
            )

        if not accepted_candidates:
            return _no_change_section_result(
                section_text=section_text,
                strategy=strategy,
                failure_reasons=failure_reasons or ["no_accepted_candidate"],
                candidate_count=candidate_count,
                best_candidate_ai_score=best_candidate_ai_score,
                retry_recommended=True,
            )

        accepted_candidates.sort(key=lambda item: item[0])
        _rank, best_rewrite, used_rewriter, accepted_ai_score = accepted_candidates[0]
        return {
            "rewritten_text": best_rewrite.strip(),
            "paragraphs_targeted": len(_split_paragraphs(section_text)),
            "paragraphs_accepted": len(_split_paragraphs(best_rewrite)) or 1,
            "paragraphs_rejected_drift": 0,
            "rewriter_used": used_rewriter,
            "changed": best_rewrite.strip() != section_text.strip(),
            "failure_reasons": failure_reasons,
            "strategy": strategy,
            "candidate_count": candidate_count,
            "accepted_candidate_count": len(accepted_candidates),
            "best_candidate_ai_score": accepted_ai_score,
            "best_candidate_overlap_score": None,
            "retry_recommended": False,
        }

    def rewrite_section(
        self,
        section_text: str,
        ai_scores: dict[str, float],
        style_persona: str = "Academic but conversational",
        *,
        section_name: str | None = None,
        force_rewrite: bool = False,
        require_quality_improvement: bool = True,
        remediation_context: dict[str, Any] | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        paragraphs = _split_paragraphs(section_text)
        if not paragraphs:
            return {
                "rewritten_text": section_text,
                "paragraphs_targeted": 0,
                "paragraphs_accepted": 0,
                "paragraphs_rejected_drift": 0,
                "rewriter_used": "none",
                "changed": False,
                "failure_reasons": [],
                "strategy": strategy,
                "candidate_count": 0,
                "accepted_candidate_count": 0,
                "best_candidate_ai_score": None,
                "best_candidate_overlap_score": None,
                "retry_recommended": False,
            }

        persona = style_persona or SECTION_STYLE_PERSONAS.get(section_name or "", "Academic but conversational")
        if force_rewrite and self.config.full_section_rewrite:
            return self._rewrite_full_section(
                section_text=section_text,
                section_name=section_name or "section",
                ai_scores=ai_scores,
                style_persona=persona,
                remediation_context=remediation_context,
                strategy=strategy or _strategy_for_iteration(0, self.config.strategy_order),
            )

        scored_paragraphs: list[tuple[int, dict[str, float], str]] = []
        all_scored_paragraphs: list[tuple[int, dict[str, float], str]] = []
        for index, paragraph in enumerate(paragraphs):
            paragraph_scores = composite_ai_score(paragraph)
            paragraph_detection = _score_candidate_text(self.detector_scorer, paragraph)
            if paragraph_detection.score is not None:
                paragraph_scores["desklib_score"] = paragraph_detection.score
            all_scored_paragraphs.append((index, paragraph_scores, paragraph))
            if (
                paragraph_scores.get("composite_score", 0.0) > self.config.max_ai_pattern_score_to_pass
                or paragraph_scores.get("burstiness", 0.0) < self.config.min_burstiness_to_pass
                or paragraph_scores.get("desklib_score", 0.0) > 0.10
            ):
                scored_paragraphs.append((index, paragraph_scores, paragraph))

        scored_paragraphs.sort(
            key=lambda item: (
                item[1].get("desklib_score", 0.0),
                item[1].get("composite_score", 0.0),
                1.0 - item[1].get("burstiness", 0.0),
            ),
            reverse=True,
        )
        targets = scored_paragraphs[: self.config.max_target_paragraphs_per_section]
        if force_rewrite and not targets:
            targets = _select_substantive_paragraph_targets(
                all_scored_paragraphs,
                limit=self.config.max_target_paragraphs_per_section,
            )
        if not targets:
            return {
                "rewritten_text": section_text,
                "paragraphs_targeted": 0,
                "paragraphs_accepted": 0,
                "paragraphs_rejected_drift": 0,
                "rewriter_used": "none",
                "changed": False,
                "failure_reasons": [],
                "strategy": strategy,
                "candidate_count": 0,
                "accepted_candidate_count": 0,
                "best_candidate_ai_score": None,
                "best_candidate_overlap_score": None,
                "retry_recommended": False,
            }

        accepted = 0
        rejected_drift = 0
        rewriter_modes: set[str] = set()
        failure_reasons: list[str] = []
        updated = list(paragraphs)
        for index, paragraph_scores, original_paragraph in targets:
            original_detection = _score_candidate_text(self.detector_scorer, original_paragraph)
            if self.detector_scorer is not None and original_detection.score is None:
                _append_reason(
                    failure_reasons,
                    original_detection.failure_reason or "desklib_scorer_unavailable",
                )
                continue

            protected_text, spans = extract_protected_spans(original_paragraph)
            attempts = _rewrite_paragraph_candidates(
                self.backend,
                target_para=protected_text,
                section_context=section_text,
                style_persona=persona,
                ai_scores=paragraph_scores,
                candidate_count=self.config.rewrite_candidate_count,
                rewrite_mode=self.config.rewrite_mode,
            )
            accepted_candidates: list[tuple[tuple[float, ...], str, str]] = []
            for attempt in attempts:
                if not attempt.changed:
                    if attempt.failure_reason:
                        _append_reason(failure_reasons, attempt.failure_reason)
                    continue

                rewritten = restore_protected_spans(attempt.text.strip(), spans)
                rewritten_scores = composite_ai_score(rewritten)
                candidate_detection = _score_candidate_text(self.detector_scorer, rewritten)
                if self.detector_scorer is not None:
                    if candidate_detection.score is None:
                        _append_reason(
                            failure_reasons,
                            candidate_detection.failure_reason or "desklib_scoring_failed",
                        )
                        continue
                    if (
                        self.config.require_desklib_candidate_improvement
                        and not _desklib_score_improves(
                            original_score=original_detection.score,
                            candidate_score=candidate_detection.score,
                            min_improvement=_required_desklib_drop(
                                original_score=original_detection.score,
                                config=self.config,
                            ),
                        )
                    ):
                        _append_reason(failure_reasons, "desklib_not_improved")
                        continue

                quality_improved = _rewrite_improves_quality(
                    original_scores=paragraph_scores,
                    rewritten_scores=rewritten_scores,
                )
                if (
                    self.detector_scorer is None
                    and require_quality_improvement
                    and not quality_improved
                ):
                    _append_reason(failure_reasons, "quality_not_improved")
                    continue

                drift_value = self.semantic_drift.drift(original_paragraph, rewritten)
                drift_threshold = _effective_semantic_drift_threshold(
                    semantic_checker=self.semantic_drift,
                    configured_threshold=self.config.semantic_drift_threshold,
                )
                if drift_value is not None and drift_value > drift_threshold:
                    rejected_drift += 1
                    _append_reason(failure_reasons, "semantic_drift")
                    logger.warning(
                        "Rejected rewrite for paragraph %s because semantic drift %.3f exceeded threshold %.3f.",
                        index,
                        drift_value,
                        drift_threshold,
                    )
                    continue

                safety = verify_rewrite_safety(
                    original=original_paragraph,
                    rewritten=rewritten,
                    similarity_threshold=_effective_similarity_threshold(
                        semantic_checker=self.semantic_drift,
                        configured_threshold=self.config.semantic_drift_threshold,
                    ),
                )
                if not safety.passed:
                    rejected_drift += 1
                    _append_reason(failure_reasons, _map_safety_failure_reason(safety.reasons))
                    logger.warning(
                        "Rejected rewrite for paragraph %s because safety checks failed: %s",
                        index,
                        ",".join(safety.reasons),
                    )
                    continue

                accepted_candidates.append(
                    (
                        _candidate_rank_key(
                            original=original_paragraph,
                            rewritten=rewritten,
                            rewritten_scores=rewritten_scores,
                            desklib_score=candidate_detection.score,
                            drift_value=drift_value,
                            safety_similarity=float(getattr(safety, "similarity", 1.0)),
                            quality_improved=quality_improved,
                        ),
                        rewritten,
                        attempt.rewriter_used,
                    )
                )

            if not accepted_candidates:
                continue

            accepted_candidates.sort(key=lambda item: item[0])
            _, best_rewrite, used_rewriter = accepted_candidates[0]
            updated[index] = best_rewrite
            accepted += 1
            rewriter_modes.add(used_rewriter)

        used = _resolve_used_rewriter(rewriter_modes)
        return {
            "rewritten_text": "\n\n".join(updated).strip(),
            "paragraphs_targeted": len(targets),
            "paragraphs_accepted": accepted,
            "paragraphs_rejected_drift": rejected_drift,
            "rewriter_used": used,
            "changed": accepted > 0,
            "failure_reasons": failure_reasons,
            "strategy": strategy,
            "candidate_count": 0,
            "accepted_candidate_count": accepted,
            "best_candidate_ai_score": None,
            "best_candidate_overlap_score": None,
            "retry_recommended": False,
        }


class HybridSectionRewriter:
    """Compatibility wrapper around the new humanizer rewriter."""

    def __init__(
        self,
        *,
        config: HumanizerConfig | None = None,
        vertex_client: Any | None = None,
        perplexity_scorer: Any | None = None,
    ):
        del vertex_client, perplexity_scorer
        self.config = config or HumanizerConfig.from_settings()
        self._rewriter = HumanizerRewriter(self.config)

    async def humanize_section(
        self,
        *,
        section_name: str,
        text: str,
        section_confidence: float | None = None,
        trace_id: str,
        logger_: logging.Logger | None = None,
    ) -> CompatibilityRewriteOutcome:
        del section_confidence, trace_id, logger_
        before = composite_ai_score(text)
        rewrite_result = self._rewriter.rewrite_section(
            section_text=text,
            ai_scores=before,
            style_persona=SECTION_STYLE_PERSONAS.get(section_name, "Academic but conversational"),
            section_name=section_name,
        )
        after_text = rewrite_result["rewritten_text"]
        after = composite_ai_score(after_text)
        applied_changes: list[str] = []
        if rewrite_result["paragraphs_targeted"]:
            applied_changes.append(
                f"Targeted {rewrite_result['paragraphs_targeted']} paragraph(s) with {rewrite_result['rewriter_used']} rewriting."
            )
        if rewrite_result["paragraphs_rejected_drift"]:
            applied_changes.append(
                f"Rejected {rewrite_result['paragraphs_rejected_drift']} paragraph(s) for semantic drift."
            )
        return CompatibilityRewriteOutcome(
            text=after_text,
            applied_changes=applied_changes,
            analysis_before=CompatibilityAnalysis(ai_pattern_score=before["composite_score"]),
            analysis_after=CompatibilityAnalysis(ai_pattern_score=after["composite_score"]),
        )


def _split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", (text or "").strip()) if paragraph.strip()]


def _select_substantive_paragraph_targets(
    scored_paragraphs: list[tuple[int, dict[str, float], str]],
    *,
    limit: int,
) -> list[tuple[int, dict[str, float], str]]:
    """Select fallback targets when the external detector flagged a section."""

    substantive = [
        item
        for item in scored_paragraphs
        if _word_count(item[2]) >= 12
    ]
    candidates = substantive or scored_paragraphs
    candidates.sort(
        key=lambda item: (
            _word_count(item[2]),
            item[1].get("composite_score", 0.0),
            len(item[2]),
        ),
        reverse=True,
    )
    return candidates[: max(1, limit)]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def _rewrite_paragraph_candidates(
    backend: Any,
    *,
    target_para: str,
    section_context: str,
    style_persona: str,
    ai_scores: dict[str, float],
    candidate_count: int,
    rewrite_mode: str,
) -> list[RewriteAttemptResult]:
    if hasattr(backend, "rewrite_paragraph_candidates"):
        return list(
            backend.rewrite_paragraph_candidates(
                target_para=target_para,
                section_context=section_context,
                style_persona=style_persona,
                ai_scores=ai_scores,
                candidate_count=candidate_count,
                rewrite_mode=rewrite_mode,
            )
        )
    return [
        backend.rewrite_paragraph(
            target_para=target_para,
            section_context=section_context,
            style_persona=style_persona,
            ai_scores=ai_scores,
        )
    ]


def _rewrite_section_candidates(
    backend: Any,
    *,
    section_text: str,
    section_name: str,
    style_persona: str,
    remediation_context: dict[str, Any] | None,
    strategy: str,
    candidate_count: int,
) -> list[RewriteAttemptResult]:
    if hasattr(backend, "rewrite_section_candidates"):
        return list(
            backend.rewrite_section_candidates(
                section_text=section_text,
                section_name=section_name,
                style_persona=style_persona,
                remediation_context=remediation_context,
                strategy=strategy,
                candidate_count=candidate_count,
            )
        )
    return [
        RewriteAttemptResult(
            text=section_text,
            rewriter_used="none",
            changed=False,
            failure_reason="backend_disabled",
        )
    ]


def _no_change_section_result(
    *,
    section_text: str,
    strategy: str | None,
    failure_reasons: list[str],
    candidate_count: int = 0,
    best_candidate_ai_score: float | None = None,
    retry_recommended: bool = False,
) -> dict[str, Any]:
    return {
        "rewritten_text": section_text,
        "paragraphs_targeted": len(_split_paragraphs(section_text)),
        "paragraphs_accepted": 0,
        "paragraphs_rejected_drift": 0,
        "rewriter_used": "none",
        "changed": False,
        "failure_reasons": failure_reasons,
        "strategy": strategy,
        "candidate_count": candidate_count,
        "accepted_candidate_count": 0,
        "best_candidate_ai_score": best_candidate_ai_score,
        "best_candidate_overlap_score": None,
        "retry_recommended": retry_recommended,
    }


def _strategy_for_iteration(iteration: int, strategy_order: tuple[str, ...]) -> str:
    strategies = tuple(item.strip() for item in strategy_order if str(item).strip()) or (
        "evidence_section",
        "detector_feedback",
        "overlap_reduction",
    )
    index = min(max(0, int(iteration or 0)), len(strategies) - 1)
    return strategies[index]


def _effective_semantic_drift_threshold(
    *,
    semantic_checker: SemanticDriftChecker,
    configured_threshold: float,
) -> float:
    threshold = max(0.0, min(1.0, float(configured_threshold)))
    if getattr(semantic_checker, "available", False):
        return threshold

    # When the embedding model is unavailable, drift() falls back to token/sequence
    # similarity. That heuristic is useful but harsher for valid paraphrases, so align
    # it with the independent safety similarity gate instead of rejecting good rewrites.
    fallback_threshold = 1.0 - _effective_similarity_threshold(
        semantic_checker=semantic_checker,
        configured_threshold=threshold,
    )
    return round(max(threshold, fallback_threshold), 4)


def _effective_similarity_threshold(
    *,
    semantic_checker: SemanticDriftChecker,
    configured_threshold: float,
) -> float:
    threshold = _rewrite_similarity_threshold(configured_threshold)
    if getattr(semantic_checker, "available", False):
        return threshold
    return min(threshold, 0.5)


def _candidate_rank_key(
    *,
    original: str,
    rewritten: str,
    rewritten_scores: dict[str, float],
    desklib_score: float | None,
    drift_value: float | None,
    safety_similarity: float,
    quality_improved: bool,
) -> tuple[float, ...]:
    length_delta = abs(_word_count(original) - _word_count(rewritten)) / max(1, _word_count(original))
    return (
        float(desklib_score) if desklib_score is not None else 1.0,
        float(rewritten_scores.get("composite_score", 0.0)),
        1.0 - float(rewritten_scores.get("burstiness", 0.0)),
        float(drift_value or 0.0),
        1.0 - float(safety_similarity),
        length_delta,
        0.0 if quality_improved else 0.05,
    )


def _append_reason(reasons: list[str], reason: str) -> None:
    cleaned = str(reason or "").strip()
    if cleaned and cleaned not in reasons:
        reasons.append(cleaned)


def _score_candidate_text(
    scorer: DesklibCandidateScorer | None,
    text: str,
) -> CandidateDetectionScore:
    if scorer is None:
        return CandidateDetectionScore(score=None, backend="none")
    return scorer.score_text(text)


def _desklib_score_improves(
    *,
    original_score: float | None,
    candidate_score: float | None,
    min_improvement: float,
) -> bool:
    if original_score is None or candidate_score is None:
        return False
    if candidate_score <= 0.10:
        return True
    return candidate_score <= original_score - max(0.0, float(min_improvement))


def _required_desklib_drop(
    *,
    original_score: float | None,
    config: HumanizerConfig,
) -> float:
    if original_score is None:
        return config.desklib_candidate_min_improvement
    if original_score > 0.90:
        return config.accept_min_ai_drop_high
    if original_score > 0.35:
        return config.accept_min_ai_drop_medium
    return config.desklib_candidate_min_improvement


def _rewrite_similarity_threshold(semantic_drift_threshold: float) -> float:
    return round(max(0.5, 0.68 - (max(0.0, min(1.0, semantic_drift_threshold)) * 0.2)), 4)


def _rewrite_improves_quality(
    *,
    original_scores: dict[str, float],
    rewritten_scores: dict[str, float],
) -> bool:
    original_composite = float(original_scores.get("composite_score", 0.0))
    rewritten_composite = float(rewritten_scores.get("composite_score", 0.0))
    composite_gain = original_composite - rewritten_composite
    burstiness_gain = float(rewritten_scores.get("burstiness", 0.0)) - float(
        original_scores.get("burstiness", 0.0),
    )
    transition_gain = float(original_scores.get("transition_uniformity", 0.0)) - float(
        rewritten_scores.get("transition_uniformity", 0.0),
    )
    cadence_gain = float(original_scores.get("cadence_uniformity", 0.0)) - float(
        rewritten_scores.get("cadence_uniformity", 0.0),
    )
    return (
        composite_gain >= 0.03
        or (
            composite_gain >= 0.0
            and (
                burstiness_gain >= 0.08
                or transition_gain >= 0.08
                or cadence_gain >= 0.08
            )
        )
    )


def _build_hf_prompt(
    *,
    target_para: str,
    section_context: str,
    style_persona: str,
    model_id: str,
) -> str:
    if model_id.strip().lower() == "aventiq-ai/t5-paraphrase-generation":
        return target_para
    trimmed_context = section_context[:1200]
    return (
        "paraphrase: Rewrite the academic paragraph below so it sounds naturally human-written "
        "without changing meaning, citations, numbers, latex, or technical entities.\n"
        f"Style: {style_persona}\n"
        f"Context: {trimmed_context}\n"
        f"Paragraph: {target_para}"
    )


def _build_vertex_candidate_prompt(
    *,
    target_para: str,
    section_context: str,
    style_persona: str,
    ai_scores: dict[str, float],
    candidate_count: int,
    rewrite_mode: str,
) -> str:
    mode_instruction = {
        "conservative": "Make light edits. Preserve most phrasing while adding natural rhythm.",
        "standard": "Make moderate edits. Vary sentence rhythm, transitions, and word choice.",
        "deep": "Make stronger structural edits while preserving every factual claim.",
        "academic-natural": (
            "Use natural academic prose. Keep the authorial voice scholarly, precise, and less templated."
        ),
    }.get((rewrite_mode or "standard").strip().lower(), "Make moderate naturalness edits.")
    trimmed_context = section_context[:1600]
    return (
        "You are rewriting one academic manuscript paragraph for clarity and natural human cadence.\n"
        "Do not add new claims. Do not remove, add, or change citations, numbers, percentages, equations, "
        "LaTeX commands, dataset names, model names, or technical entities.\n"
        f"Return exactly {candidate_count} alternatives as a strict JSON array of strings. "
        "No markdown, no commentary, no keys.\n\n"
        f"REWRITE MODE: {rewrite_mode}\n"
        f"MODE GUIDANCE: {mode_instruction}\n"
        f"STYLE TARGET: {style_persona}\n"
        f"BURSTINESS SCORE: {ai_scores.get('burstiness', 0.0):.2f}\n"
        f"CADENCE UNIFORMITY: {ai_scores.get('cadence_uniformity', 0.0):.2f}\n"
        f"TRANSITION UNIFORMITY: {ai_scores.get('transition_uniformity', 0.0):.2f}\n\n"
        "SECTION CONTEXT:\n"
        f"{trimmed_context}\n\n"
        "PARAGRAPH:\n"
        f"{target_para}\n"
    )


def _build_vertex_section_candidate_prompt(
    *,
    section_text: str,
    section_name: str,
    style_persona: str,
    remediation_context: dict[str, Any] | None,
    strategy: str,
    candidate_count: int,
) -> str:
    strategy_key = (strategy or "evidence_section").strip().lower()
    strategy_guidance = {
        "evidence_section": (
            "Rebuild the section from the evidence notes and citation map, not by paraphrasing "
            "the old prose sentence by sentence."
        ),
        "detector_feedback": (
            "Reduce formulaic academic patterns: vary sentence openings, sentence lengths, "
            "transition rhythm, and claim ordering while keeping the same evidence."
        ),
        "overlap_reduction": (
            "Avoid close source phrasing. Express the same source-backed claims using fresh "
            "sentence structures and synthesis."
        ),
    }.get(strategy_key, "Create a fresh, source-grounded academic rewrite with natural cadence.")
    context_payload = _compact_remediation_context(remediation_context, section_name=section_name)
    trimmed_section = section_text[:6500]
    return (
        "You are revising one section of an academic manuscript for an integrity-first SaaS workflow.\n"
        "Goal: produce safer, more natural academic prose while preserving meaning and evidence.\n"
        "Do not invent claims. Do not remove, add, or change citations, numbers, percentages, equations, "
        "LaTeX commands, dataset names, model names, or technical entities. Keep section scope and tense.\n"
        f"Return exactly {candidate_count} full-section alternatives as a strict JSON array of strings. "
        "No markdown, no commentary, no keys.\n\n"
        f"SECTION: {section_name}\n"
        f"STYLE TARGET: {style_persona}\n"
        f"STRATEGY: {strategy_key}\n"
        f"STRATEGY GUIDANCE: {strategy_guidance}\n\n"
        "EVIDENCE / REMEDIATION CONTEXT:\n"
        f"{context_payload}\n\n"
        "CURRENT SECTION:\n"
        f"{trimmed_section}\n"
    )


def _compact_remediation_context(
    remediation_context: dict[str, Any] | None,
    *,
    section_name: str,
) -> str:
    if not isinstance(remediation_context, dict):
        return "No structured evidence context was provided; preserve the section's existing claims."

    sections = remediation_context.get("sections")
    section_payload = sections.get(section_name) if isinstance(sections, dict) else None
    if not isinstance(section_payload, dict):
        return "No section-specific evidence context was provided; preserve the section's existing claims."

    def _items(key: str, limit: int = 5) -> list[str]:
        raw = section_payload.get(key) or []
        if isinstance(raw, str):
            values = [raw]
        else:
            values = list(raw) if isinstance(raw, (list, tuple)) else []
        return [str(item).strip()[:260] for item in values if str(item).strip()][:limit]

    compact = {
        "key_points": _items("key_points", 6),
        "direct_evidence": _items("direct_evidence", 6),
        "inferred_synthesis": _items("inferred_synthesis", 5),
        "missing_evidence": _items("missing_evidence", 4),
        "source_span_ids": _items("source_span_ids", 8),
        "citation_map": _items("citation_map", 8),
    }
    return json.dumps(compact, ensure_ascii=True)


def _normalize_model_candidates(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw).strip()

    parsed: object | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = literal_eval(raw)
        except (SyntaxError, ValueError):
            parsed = None

    if isinstance(parsed, list):
        values = [str(item).strip() for item in parsed if str(item).strip()]
    elif isinstance(parsed, dict):
        values = [
            str(value).strip()
            for key, value in parsed.items()
            if str(key).lower().startswith(("candidate", "option", "rewrite"))
            and str(value).strip()
        ]
    else:
        values = []

    if not values:
        numbered = re.split(r"(?:^|\n)\s*(?:candidate|option)?\s*\d+[\).:-]\s*", raw, flags=re.IGNORECASE)
        values = [part.strip() for part in numbered if part.strip()]

    if not values:
        values = [_normalize_model_output(raw)]

    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_model_output(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def _normalize_model_output(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("[") and normalized.endswith("]"):
        try:
            parsed = literal_eval(normalized)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            candidates = [str(item).strip() for item in parsed if str(item).strip()]
            if candidates:
                normalized = candidates[0]
    if "'." not in normalized and "', '" in normalized:
        normalized = re.split(r"'\s*,\s*'", normalized, maxsplit=1)[0]
    elif "', '" in normalized:
        normalized = re.split(r"'\s*,\s*'", normalized, maxsplit=1)[0]
    normalized = re.sub(r"^\s*(rewritten paragraph|rewrite|output)\s*:\s*", "", normalized, flags=re.IGNORECASE)
    lines = [line.strip(" \"'") for line in normalized.splitlines() if line.strip()]
    if not lines:
        return ""
    normalized = " ".join(lines)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    return normalized.strip()


def _map_safety_failure_reason(reasons: list[str]) -> str:
    joined = ",".join(reasons)
    lowered = joined.lower()
    if "citation" in lowered:
        return "protected_span_changed"
    if "latex" in lowered:
        return "protected_span_changed"
    if "number" in lowered:
        return "protected_span_changed"
    if "similarity" in lowered:
        return "similarity_too_low"
    return "protected_span_changed"


def _resolve_used_rewriter(rewriter_modes: set[str]) -> str:
    if not rewriter_modes:
        return "none"
    if len(rewriter_modes) == 1:
        return next(iter(rewriter_modes))
    return "mixed"


__all__ = [
    "VertexRewriter",
    "HuggingFaceRewriter",
    "NoChangeRewriter",
    "DesklibCandidateScorer",
    "DeterministicRewriter",
    "HumanizerRewriter",
    "HybridSectionRewriter",
    "CandidateDetectionScore",
]
