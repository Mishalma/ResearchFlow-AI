"""Paragraph rewriting backends for the humanizer agent."""

from __future__ import annotations

import logging
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


class VertexRewriter:
    """Vertex-backed paragraph rewriter."""

    backend_name = "vertex"

    def __init__(self, project: str, location: str, model: str = "gemini-1.5-pro"):
        self.project = project
        self.location = location
        self.model = model
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
                rewritten = future.result(timeout=_MODEL_TIMEOUT_SECONDS)
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


class HumanizerRewriter:
    """Main humanizer rewrite interface with model-only no-change failure behavior."""

    def __init__(self, config: HumanizerConfig | None):
        self.config = config or HumanizerConfig.from_settings()
        self.mode = self.config.runtime_mode
        self.semantic_drift = SemanticDriftChecker()
        self.backend = self._build_backend()
        logger.info(
            "HumanizerRewriter initialized in %s mode with backend=%s.",
            self.mode,
            self.config.selected_rewriter_backend,
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
            )
        return NoChangeRewriter()

    def rewrite_section(
        self,
        section_text: str,
        ai_scores: dict[str, float],
        style_persona: str = "Academic but conversational",
        *,
        section_name: str | None = None,
    ) -> dict[str, Any]:
        del ai_scores
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
            }

        scored_paragraphs: list[tuple[int, dict[str, float], str]] = []
        for index, paragraph in enumerate(paragraphs):
            paragraph_scores = composite_ai_score(paragraph)
            if (
                paragraph_scores.get("composite_score", 0.0) > self.config.max_ai_pattern_score_to_pass
                or paragraph_scores.get("burstiness", 0.0) < self.config.min_burstiness_to_pass
            ):
                scored_paragraphs.append((index, paragraph_scores, paragraph))

        scored_paragraphs.sort(
            key=lambda item: (
                item[1].get("composite_score", 0.0),
                1.0 - item[1].get("burstiness", 0.0),
            ),
            reverse=True,
        )
        targets = scored_paragraphs[: self.config.max_target_paragraphs_per_section]
        if not targets:
            return {
                "rewritten_text": section_text,
                "paragraphs_targeted": 0,
                "paragraphs_accepted": 0,
                "paragraphs_rejected_drift": 0,
                "rewriter_used": "none",
                "changed": False,
                "failure_reasons": [],
            }

        accepted = 0
        rejected_drift = 0
        rewriter_modes: set[str] = set()
        failure_reasons: list[str] = []
        updated = list(paragraphs)
        persona = style_persona or SECTION_STYLE_PERSONAS.get(section_name or "", "Academic but conversational")

        for index, paragraph_scores, original_paragraph in targets:
            protected_text, spans = extract_protected_spans(original_paragraph)
            attempt = self.backend.rewrite_paragraph(
                target_para=protected_text,
                section_context=section_text,
                style_persona=persona,
                ai_scores=paragraph_scores,
            )
            if not attempt.changed:
                if attempt.failure_reason:
                    failure_reasons.append(attempt.failure_reason)
                continue

            rewritten = restore_protected_spans(attempt.text.strip(), spans)
            rewritten_scores = composite_ai_score(rewritten)
            if not _rewrite_improves_quality(
                original_scores=paragraph_scores,
                rewritten_scores=rewritten_scores,
            ):
                failure_reasons.append("quality_not_improved")
                continue

            drift_value = self.semantic_drift.drift(original_paragraph, rewritten)
            if drift_value is not None and drift_value > self.config.semantic_drift_threshold:
                rejected_drift += 1
                failure_reasons.append("semantic_drift")
                logger.warning(
                    "Rejected rewrite for paragraph %s because semantic drift %.3f exceeded threshold %.3f.",
                    index,
                    drift_value,
                    self.config.semantic_drift_threshold,
                )
                continue

            safety = verify_rewrite_safety(
                original=original_paragraph,
                rewritten=rewritten,
                similarity_threshold=_rewrite_similarity_threshold(
                    self.config.semantic_drift_threshold,
                ),
            )
            if not safety.passed:
                rejected_drift += 1
                failure_reasons.append(_map_safety_failure_reason(safety.reasons))
                logger.warning(
                    "Rejected rewrite for paragraph %s because safety checks failed: %s",
                    index,
                    ",".join(safety.reasons),
                )
                continue

            updated[index] = rewritten
            accepted += 1
            rewriter_modes.add(attempt.rewriter_used)

        used = _resolve_used_rewriter(rewriter_modes)
        return {
            "rewritten_text": "\n\n".join(updated).strip(),
            "paragraphs_targeted": len(targets),
            "paragraphs_accepted": accepted,
            "paragraphs_rejected_drift": rejected_drift,
            "rewriter_used": used,
            "changed": accepted > 0,
            "failure_reasons": failure_reasons,
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
    "DeterministicRewriter",
    "HumanizerRewriter",
    "HybridSectionRewriter",
]
