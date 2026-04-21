"""Paragraph rewriting backends for the humanizer agent."""

from __future__ import annotations

import logging
import random
import re
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
TAILING_NEGATION_PATTERN = re.compile(r"[,—]\s*no ([a-z][a-z-]*)([.!?])", re.IGNORECASE)
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


class VertexRewriter:
    """Primary Vertex-backed paragraph rewriter."""

    def __init__(self, project: str, location: str, model: str = "gemini-1.5-pro"):
        self.project = project
        self.location = location
        self.model = model
        self.available = False
        self._client = None

        if not project or not location:
            logger.warning(
                "VertexRewriter disabled because project or location is missing.",
            )
            return

        try:
            from google import genai
            from google.genai import types

            self._genai_types = types
            self._client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=types.HttpOptions(api_version="v1"),
            )
            self.available = True
        except Exception as exc:  # pragma: no cover - dependency/runtime dependent
            logger.warning("VertexRewriter initialization failed: %s", exc)

    def rewrite_paragraph(
        self,
        target_para: str,
        section_context: str,
        style_persona: str,
        ai_scores: dict[str, float],
    ) -> str:
        """Rewrite one paragraph with Vertex while preserving meaning and citations."""

        if not self.available or self._client is None:
            return target_para

        prompt = (
            "You are rewriting one paragraph from an academic manuscript to sound authentically "
            "human-written. Do not change the meaning, citations, or factual content.\n\n"
            f"STYLE TARGET: {style_persona}\n\n"
            "DETECTED AI PATTERNS TO FIX:\n"
            f"- Burstiness score: {ai_scores.get('burstiness', 0.0):.2f} (target > 0.45)\n"
            f"- Cadence uniformity: {ai_scores.get('cadence_uniformity', 0.0):.2f} (target < 0.4)\n"
            f"- Flagged transitions: {ai_scores.get('transition_uniformity', 0.0):.2f} (target < 0.1)\n\n"
            "FULL SECTION CONTEXT (read for tone and flow — do not rewrite):\n"
            f"{section_context}\n\n"
            "PARAGRAPH TO REWRITE:\n"
            f"{target_para}\n\n"
            "REWRITING RULES:\n"
            "1. Vary sentence length aggressively — mix short punchy sentences (5–8 words) "
            "with longer complex ones (25–40 words). Aim for burstiness > 0.5.\n"
            "2. Break subject-verb-object monotony — use fronted adverbials, participial "
            "phrases, and inverted syntax occasionally.\n"
            "3. Remove ALL of these phrases: \"Furthermore\", \"Moreover\", \"In addition\", "
            "\"It is worth noting\", \"It is important to note\", \"Notably\", \"Importantly\","
            "\n   \"In conclusion\", \"This study aims to\".\n"
            "4. Add ONE concrete real-world anchor or sensory detail if it fits naturally.\n"
            "5. Use em-dashes and parentheticals at least once if the paragraph is > 4 sentences.\n"
            "6. Preserve all citation markers exactly (e.g. [1], (Smith, 2020), etc.)\n"
            "7. Output ONLY the rewritten paragraph. No preamble, no explanation.\n"
        )

        def _call_vertex() -> str:
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self.model,
                contents=prompt,
            )
            return (getattr(response, "text", "") or "").strip()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_vertex)
                rewritten = future.result(timeout=15)
            return rewritten or target_para
        except FuturesTimeoutError:
            logger.error("Vertex rewrite timed out after 15 seconds.")
            return target_para
        except Exception as exc:  # pragma: no cover - provider dependent
            logger.error("Vertex rewrite failed: %s", exc)
            return target_para


class DeterministicRewriter:
    """Fallback paragraph rewriter using layered structural transforms."""

    def transition_strip(self, text: str) -> str:
        """Replace repeated stock transitions with more varied alternatives."""

        rewritten = text
        for source, choices in TRANSITION_REPLACEMENTS.items():
            replacement = _RANDOM.choice(choices)
            rewritten = re.sub(
                re.escape(source),
                replacement,
                rewritten,
                flags=re.IGNORECASE,
            )
        rewritten = re.sub(r"\s{2,}", " ", rewritten)
        rewritten = re.sub(r"\s+([,.;:])", r"\1", rewritten)
        return rewritten.strip()

    def sentence_split(self, text: str) -> str:
        """Split long sentences once at the first eligible conjunction."""

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
        """Fuse consecutive short sentences into more varied combined lines."""

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
        """Front up to two result-style sentences with adverbial variation."""

        sentences = split_sentences(text)
        fronted: list[str] = []
        rewrites = 0
        pattern = re.compile(
            r"^(The\s+(?:results|data|analysis|findings)\b.*)$",
            re.IGNORECASE,
        )
        for sentence in sentences:
            if rewrites < 2 and pattern.match(sentence):
                adverb = _RANDOM.choice(FRONTING_ADVERBS)
                fronted.append(f"{adverb} {sentence[:1].lower()}{sentence[1:]}")
                rewrites += 1
            else:
                fronted.append(sentence)
        return " ".join(fronted).strip()

    def qualifier_variation(self, text: str) -> str:
        """Vary a small set of overused academic verbs and stock phrases."""

        rewritten = text
        for source, choices in QUALIFIER_REPLACEMENTS.items():
            replacement = _RANDOM.choice(choices)
            rewritten = re.sub(
                rf"\b{re.escape(source)}\b",
                replacement,
                rewritten,
                flags=re.IGNORECASE,
            )
        return rewritten

    def anti_ai_cleanup(self, text: str) -> str:
        """Run a final deterministic cleanup pass for obvious AI-writing artifacts."""

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
        rewritten = rewritten.replace("—", ", ")
        rewritten = rewritten.replace("“", '"').replace("”", '"').replace("’", "'")
        rewritten = re.sub(r"\s{2,}", " ", rewritten)
        rewritten = re.sub(r"\s+([,.;:!?])", r"\1", rewritten)
        rewritten = re.sub(r"([,.;:!?])([A-Za-z])", r"\1 \2", rewritten)
        rewritten = re.sub(r"\s+,", ",", rewritten)
        return rewritten.strip()

    def apply_all(self, text: str) -> str:
        """Apply all deterministic rewriting passes in sequence."""

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
    """Main humanizer rewriting interface with Vertex + deterministic fallback."""

    def __init__(self, config: HumanizerConfig | None):
        self.config = config or HumanizerConfig.from_settings()
        self.mode = self.config.runtime_mode
        self.deterministic = DeterministicRewriter()
        self.semantic_drift = SemanticDriftChecker()
        self.vertex = None
        if self.config.model_rewriter_enabled:
            self.vertex = VertexRewriter(
                project=self.config.google_project,
                location=self.config.google_location,
                model=self.config.vertex_model or "gemini-1.5-pro",
            )
        logger.info("HumanizerRewriter initialized in %s mode.", self.mode)

    def rewrite_section(
        self,
        section_text: str,
        ai_scores: dict[str, float],
        style_persona: str = "Academic but conversational",
        *,
        section_name: str | None = None,
    ) -> dict[str, Any]:
        """Rewrite the most AI-like paragraphs in one section."""

        paragraphs = _split_paragraphs(section_text)
        if not paragraphs:
            return {
                "rewritten_text": section_text,
                "paragraphs_targeted": 0,
                "paragraphs_accepted": 0,
                "paragraphs_rejected_drift": 0,
                "rewriter_used": "deterministic" if self.mode == "lite" else "vertex",
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

        accepted = 0
        rejected_drift = 0
        rewriter_modes: set[str] = set()
        updated = list(paragraphs)
        persona = style_persona or SECTION_STYLE_PERSONAS.get(
            section_name or "",
            "Academic but conversational",
        )

        for index, paragraph_scores, original_paragraph in targets:
            rewritten = original_paragraph
            rewriter_used = "deterministic"
            if self.vertex is not None and self.vertex.available:
                candidate = self.vertex.rewrite_paragraph(
                    target_para=original_paragraph,
                    section_context=section_text,
                    style_persona=persona,
                    ai_scores=paragraph_scores,
                )
                if candidate.strip() != original_paragraph.strip():
                    rewritten = candidate.strip()
                    rewriter_used = "vertex"
                else:
                    protected_text, spans = extract_protected_spans(original_paragraph)
                    rewritten = restore_protected_spans(
                        self.deterministic.apply_all(protected_text),
                        spans,
                    )
            else:
                protected_text, spans = extract_protected_spans(original_paragraph)
                rewritten = restore_protected_spans(
                    self.deterministic.apply_all(protected_text),
                    spans,
                )

            cleaned = self.deterministic.anti_ai_cleanup(rewritten)
            if cleaned != rewritten:
                cleaned_scores = composite_ai_score(cleaned)
                if _audit_cleanup_is_acceptable(
                    baseline_scores=composite_ai_score(rewritten),
                    cleaned_scores=cleaned_scores,
                ):
                    rewritten = cleaned

            rewritten_scores = composite_ai_score(rewritten)
            if not _rewrite_improves_quality(
                original_scores=paragraph_scores,
                rewritten_scores=rewritten_scores,
            ):
                if rewriter_used == "vertex":
                    protected_text, spans = extract_protected_spans(original_paragraph)
                    fallback = restore_protected_spans(
                        self.deterministic.apply_all(protected_text),
                        spans,
                    )
                    fallback_scores = composite_ai_score(fallback)
                    if _rewrite_improves_quality(
                        original_scores=paragraph_scores,
                        rewritten_scores=fallback_scores,
                    ):
                        rewritten = fallback
                        rewritten_scores = fallback_scores
                        rewriter_used = "deterministic"
                    else:
                        continue
                else:
                    continue

            drift_value = self.semantic_drift.drift(original_paragraph, rewritten)
            if drift_value is not None and drift_value > self.config.semantic_drift_threshold:
                rejected_drift += 1
                logger.warning(
                    "Rejected humanizer rewrite for paragraph %s because semantic drift %.3f exceeded threshold %.3f.",
                    index,
                    drift_value,
                    self.config.semantic_drift_threshold,
                )
                if self.config.retry_on_drift and rewriter_used == "vertex":
                    protected_text, spans = extract_protected_spans(original_paragraph)
                    fallback = restore_protected_spans(
                        self.deterministic.apply_all(protected_text),
                        spans,
                    )
                    fallback_drift = self.semantic_drift.drift(original_paragraph, fallback)
                    if fallback_drift is None or fallback_drift <= self.config.semantic_drift_threshold:
                        rewritten = fallback
                        rewritten_scores = composite_ai_score(fallback)
                        rewriter_used = "deterministic"
                    else:
                        continue
                else:
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
                logger.warning(
                    "Rejected humanizer rewrite for paragraph %s because safety checks failed: %s",
                    index,
                    ",".join(safety.reasons),
                )
                continue

            updated[index] = rewritten
            accepted += 1
            rewriter_modes.add(rewriter_used)

        if not rewriter_modes:
            used = "deterministic" if self.mode == "lite" else ("vertex" if self.vertex and self.vertex.available else "deterministic")
        elif len(rewriter_modes) == 1:
            used = next(iter(rewriter_modes))
        else:
            used = "mixed"

        return {
            "rewritten_text": "\n\n".join(updated).strip(),
            "paragraphs_targeted": len(targets),
            "paragraphs_accepted": accepted,
            "paragraphs_rejected_drift": rejected_drift,
            "rewriter_used": used,
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
            style_persona=SECTION_STYLE_PERSONAS.get(
                section_name,
                "Academic but conversational",
            ),
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
    # This safety gate should catch genuine meaning changes, not block normal paraphrases.
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


def _audit_cleanup_is_acceptable(
    *,
    baseline_scores: dict[str, float],
    cleaned_scores: dict[str, float],
) -> bool:
    baseline_composite = float(baseline_scores.get("composite_score", 0.0))
    cleaned_composite = float(cleaned_scores.get("composite_score", 0.0))
    baseline_stock = float(baseline_scores.get("stock_phrase_density", 0.0))
    cleaned_stock = float(cleaned_scores.get("stock_phrase_density", 0.0))
    baseline_dash = float(baseline_scores.get("em_dash_overuse", 0.0))
    cleaned_dash = float(cleaned_scores.get("em_dash_overuse", 0.0))

    return (
        cleaned_composite <= (baseline_composite + 0.02)
        and cleaned_stock <= baseline_stock
        and cleaned_dash <= baseline_dash
    )


__all__ = [
    "VertexRewriter",
    "DeterministicRewriter",
    "HumanizerRewriter",
    "HybridSectionRewriter",
]
