from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from core.exceptions import GenerationError
from core.vertex_client import VertexGeminiClient
from humanizer.config import HumanizerConfig
from humanizer.detectors import ParagraphAnalysis, SectionAnalysis, analyze_section
from humanizer.perplexity import PerplexityMetric, PerplexityScorer
from humanizer.utils import (
    SECTION_LABELS,
    extract_protected_spans,
    join_paragraphs,
    restore_protected_spans,
    split_paragraphs,
    split_sentences,
    verify_rewrite_safety,
)

logger = logging.getLogger("papereasy.backend.humanizer.rewriter")

VERBOSE_HEDGE_REWRITES = {
    "it is worth noting that": "notably,",
    "it is important to note that": "importantly,",
    "it can be observed that": "",
    "it should be noted that": "",
}
TRANSITION_REWRITES = {
    "furthermore": "in addition",
    "moreover": "also",
    "additionally": "in addition",
    "therefore": "as a result",
    "overall": "taken together",
    "notably": "in practice",
    "consequently": "accordingly",
}
LEXICAL_REWRITES = {
    "significant": "substantial",
    "important": "salient",
    "various": "multiple",
    "numerous": "several",
    "shows": "indicates",
    "demonstrates": "indicates",
}
LOW_CONFIDENCE_HEDGES = ("may", "might", "appears", "suggests", "could", "tentative", "limited")


class ModelRewriteResponse(BaseModel):
    rewritten_text: str = Field(min_length=1)
    rewrite_notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RewriteOutcome:
    text: str
    applied_changes: list[str]
    backend: str


@dataclass(frozen=True)
class SectionRewriteOutcome:
    text: str
    iterations: int
    applied_changes: list[str]
    analysis_before: SectionAnalysis
    analysis_after: SectionAnalysis
    paragraph_perplexities_before: list[PerplexityMetric]
    paragraph_perplexities_after: list[PerplexityMetric]
    section_perplexity_before: PerplexityMetric
    section_perplexity_after: PerplexityMetric


class HybridSectionRewriter:
    def __init__(
        self,
        *,
        config: HumanizerConfig,
        vertex_client: VertexGeminiClient | None,
        perplexity_scorer: PerplexityScorer,
    ):
        self.config = config
        self.vertex_client = vertex_client
        self.perplexity_scorer = perplexity_scorer

    async def humanize_section(
        self,
        *,
        section_name: str,
        text: str,
        section_confidence: float | None = None,
        trace_id: str,
        logger_: logging.Logger | None = None,
    ) -> SectionRewriteOutcome:
        active_logger = logger_ or logger
        analysis_before = analyze_section(
            section_name=section_name,
            text=text,
            config=self.config,
            logger_=active_logger,
        )
        current_text = text.strip()
        current_analysis = analysis_before
        current_paragraph_scores = self.perplexity_scorer.score_paragraphs(current_text)
        current_section_score = self.perplexity_scorer.score_text(current_text)
        accepted_changes: list[str] = []
        iterations_completed = 0

        for iteration in range(1, self.config.max_iterations + 1):
            if current_analysis.ai_pattern_score <= self.config.ai_pattern_threshold:
                break
            iterations_completed = iteration

            paragraphs = split_paragraphs(current_text)
            target_paragraphs = _select_target_paragraphs(
                current_analysis.paragraphs,
                limit=self.config.max_target_paragraphs_per_section,
            )
            if not target_paragraphs:
                break

            improved = False
            for paragraph_analysis in target_paragraphs:
                paragraph_text = paragraphs[paragraph_analysis.paragraph_index]
                outcome = await self._rewrite_paragraph(
                    section_name=section_name,
                    paragraph_text=paragraph_text,
                    paragraph_analysis=paragraph_analysis,
                    section_confidence=section_confidence,
                    trace_id=trace_id,
                )
                if outcome.text.strip() == paragraph_text.strip():
                    continue

                safety = verify_rewrite_safety(
                    original=paragraph_text,
                    rewritten=outcome.text,
                    similarity_threshold=self.config.semantic_similarity_threshold,
                )
                if not safety.passed:
                    active_logger.info(
                        "Humanizer rejected rewrite for %s paragraph %s because %s",
                        section_name,
                        paragraph_analysis.paragraph_index,
                        ",".join(safety.reasons),
                    )
                    continue
                if section_confidence is not None and section_confidence < 0.65:
                    if _removed_required_hedging(paragraph_text, outcome.text):
                        active_logger.info(
                            "Humanizer rejected rewrite for %s paragraph %s because required hedging was removed.",
                            section_name,
                            paragraph_analysis.paragraph_index,
                        )
                        continue

                candidate_paragraphs = list(paragraphs)
                candidate_paragraphs[paragraph_analysis.paragraph_index] = outcome.text
                candidate_text = join_paragraphs(candidate_paragraphs)
                candidate_analysis = analyze_section(
                    section_name=section_name,
                    text=candidate_text,
                    config=self.config,
                    logger_=active_logger,
                )
                improvement = current_analysis.ai_pattern_score - candidate_analysis.ai_pattern_score
                if improvement < self.config.min_section_improvement and candidate_analysis.ai_pattern_score > self.config.ai_pattern_threshold:
                    continue

                current_text = candidate_text
                current_analysis = candidate_analysis
                current_paragraph_scores = self.perplexity_scorer.score_paragraphs(current_text)
                current_section_score = self.perplexity_scorer.score_text(current_text)
                accepted_changes.extend(outcome.applied_changes)
                improved = True
                break

            if not improved:
                break

        return SectionRewriteOutcome(
            text=current_text,
            iterations=iterations_completed,
            applied_changes=accepted_changes,
            analysis_before=analysis_before,
            analysis_after=current_analysis,
            paragraph_perplexities_before=self.perplexity_scorer.score_paragraphs(text),
            paragraph_perplexities_after=current_paragraph_scores,
            section_perplexity_before=self.perplexity_scorer.score_text(text),
            section_perplexity_after=current_section_score,
        )

    async def _rewrite_paragraph(
        self,
        *,
        section_name: str,
        paragraph_text: str,
        paragraph_analysis: ParagraphAnalysis,
        section_confidence: float | None,
        trace_id: str,
    ) -> RewriteOutcome:
        if self.config.use_model_rewriter and self.vertex_client is not None:
            try:
                return await self._rewrite_with_model(
                    section_name=section_name,
                    paragraph_text=paragraph_text,
                    paragraph_analysis=paragraph_analysis,
                    section_confidence=section_confidence,
                    trace_id=trace_id,
                )
            except GenerationError:
                logger.warning("Vertex paragraph rewrite failed for %s; falling back to deterministic rules.", section_name)
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                logger.warning("Unexpected model rewrite failure for %s: %s", section_name, exc)

        return self._rewrite_deterministically(
            section_name=section_name,
            paragraph_text=paragraph_text,
            paragraph_analysis=paragraph_analysis,
            section_confidence=section_confidence,
        )

    async def _rewrite_with_model(
        self,
        *,
        section_name: str,
        paragraph_text: str,
        paragraph_analysis: ParagraphAnalysis,
        section_confidence: float | None,
        trace_id: str,
    ) -> RewriteOutcome:
        protected_text, spans = extract_protected_spans(paragraph_text)
        prompt = (
            "You are the Humanizer Agent for IEEE manuscript polishing.\n"
            "Rewrite the paragraph to reduce repetitive AI-like cadence while preserving meaning, "
            "numbers, protected placeholders, citations, equations, and technical entities exactly.\n"
            "Return only JSON with rewritten_text and rewrite_notes.\n\n"
            f"Section: {SECTION_LABELS.get(section_name, section_name.title())}\n"
            f"Section constraints: {_section_constraints(section_name)}\n"
            f"Section confidence: {section_confidence if section_confidence is not None else 'unknown'}\n"
            f"Detected paragraph issues: {_serialize_paragraph_issues(paragraph_analysis)}\n"
            "Do not remove cautious uncertainty language if it is already present.\n"
            "Do not introduce new claims.\n"
            "Do not alter placeholders such as __PAPEREASY_PROTECTED_XXXX__.\n\n"
            f"Paragraph:\n{protected_text}"
        )
        response = await self.vertex_client.generate_json(
            prompt=prompt,
            response_schema=ModelRewriteResponse,
            model_name=self.config.rewriter_model,
        )
        rewritten = restore_protected_spans(response.rewritten_text, spans)
        return RewriteOutcome(
            text=rewritten,
            applied_changes=response.rewrite_notes or [f"Applied Vertex rewrite to {section_name} paragraph."],
            backend="vertex",
        )

    def _rewrite_deterministically(
        self,
        *,
        section_name: str,
        paragraph_text: str,
        paragraph_analysis: ParagraphAnalysis,
        section_confidence: float | None,
    ) -> RewriteOutcome:
        protected_text, spans = extract_protected_spans(paragraph_text)
        rewritten = protected_text
        changes: list[str] = []

        rewritten, transition_changes = _rewrite_transitions(rewritten)
        changes.extend(transition_changes)

        rewritten, hedge_changes = _rewrite_verbose_hedges(rewritten)
        changes.extend(hedge_changes)

        rewritten, cadence_changes = _diversify_cadence(
            rewritten,
            section_name=section_name,
            paragraph_analysis=paragraph_analysis,
        )
        changes.extend(cadence_changes)

        rewritten, lexical_changes = _diversify_lexicon(rewritten)
        changes.extend(lexical_changes)

        rewritten = _section_specific_cleanup(
            rewritten,
            section_name=section_name,
            section_confidence=section_confidence,
        )
        restored = restore_protected_spans(rewritten, spans)
        return RewriteOutcome(
            text=restored,
            applied_changes=changes or [f"Applied deterministic fallback rewrite to {section_name} paragraph."],
            backend="deterministic",
        )

def _serialize_paragraph_issues(paragraph_analysis: ParagraphAnalysis) -> list[str]:
    return [pattern.pattern_type for pattern in paragraph_analysis.detected_patterns] or ["stylistic_uniformity"]


def _select_target_paragraphs(
    paragraphs: list[ParagraphAnalysis],
    *,
    limit: int,
) -> list[ParagraphAnalysis]:
    ranked = sorted(
        paragraphs,
        key=lambda paragraph: (paragraph.ai_pattern_score, paragraph.cadence_score),
        reverse=True,
    )
    return [paragraph for paragraph in ranked if paragraph.ai_pattern_score > 0][:limit]


def _section_constraints(section_name: str) -> str:
    constraints = {
        "abstract": "Keep the paragraph compact, dense, and contribution-focused.",
        "methodology": "Preserve precise procedural language and reproducibility.",
        "results": "Keep evidence-first wording with no rhetorical inflation.",
        "discussion": "Allow modest rhetorical variety but preserve interpretation boundaries.",
        "limitations": "Preserve candid admissions and do not soften weaknesses.",
        "conclusion": "Keep the closing synthesis concise and avoid new claims.",
    }
    return constraints.get(section_name, "Use formal IEEE tone with restrained stylistic variation.")


def _rewrite_transitions(text: str) -> tuple[str, list[str]]:
    rewritten = text
    changes: list[str] = []
    for source, target in TRANSITION_REWRITES.items():
        pattern = re.compile(rf"(?im)^\s*{re.escape(source)}\b[:,]?\s*")
        if pattern.search(rewritten):
            replacement = f"{target}, " if target else ""
            rewritten = pattern.sub(replacement, rewritten)
            changes.append(f"Varied repeated transition '{source}'.")
    return rewritten, changes


def _rewrite_verbose_hedges(text: str) -> tuple[str, list[str]]:
    rewritten = text
    changes: list[str] = []
    for source, target in VERBOSE_HEDGE_REWRITES.items():
        pattern = re.compile(re.escape(source), re.IGNORECASE)
        if pattern.search(rewritten):
            rewritten = pattern.sub(target, rewritten)
            changes.append(f"Condensed stock hedge '{source}'.")
    rewritten = re.sub(r"\s{2,}", " ", rewritten).strip()
    return rewritten, changes


def _diversify_cadence(
    text: str,
    *,
    section_name: str,
    paragraph_analysis: ParagraphAnalysis,
) -> tuple[str, list[str]]:
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return text, []

    rewritten_sentences = list(sentences)
    changes: list[str] = []
    if paragraph_analysis.cadence_score >= 0.62:
        for index, sentence in enumerate(list(rewritten_sentences)):
            if len(sentence.split()) > 26 and ", and " in sentence:
                parts = sentence.split(", and ", 1)
                rewritten_sentences[index:index + 1] = [parts[0].strip() + ".", parts[1].strip().capitalize()]
                changes.append("Split an overly uniform long sentence to vary cadence.")
                break

    if section_name == "discussion" and len(rewritten_sentences) >= 2:
        first = rewritten_sentences[0]
        if first.lower().startswith("this"):
            rewritten_sentences[0] = "Taken together, " + first[0].lower() + first[1:]
            changes.append("Varied the discussion paragraph opening.")

    if section_name == "abstract" and len(rewritten_sentences) > 3:
        rewritten_sentences = rewritten_sentences[:3]
        changes.append("Kept the abstract compact during cadence cleanup.")

    return " ".join(rewritten_sentences).strip(), changes


def _diversify_lexicon(text: str) -> tuple[str, list[str]]:
    rewritten = text
    changes: list[str] = []
    for source, target in LEXICAL_REWRITES.items():
        pattern = re.compile(rf"\b{re.escape(source)}\b", re.IGNORECASE)
        matches = list(pattern.finditer(rewritten))
        if len(matches) >= 2:
            rewritten = pattern.sub(target, rewritten, count=1)
            changes.append(f"Reduced repeated academic word '{source}'.")
    return rewritten, changes


def _section_specific_cleanup(
    text: str,
    *,
    section_name: str,
    section_confidence: float | None,
) -> str:
    rewritten = re.sub(r"\s{2,}", " ", text).strip()
    if section_name == "methodology":
        rewritten = rewritten.replace("In practice,", "")
    if section_name == "results":
        rewritten = rewritten.replace("clearly ", "")
    if section_name == "limitations":
        rewritten = rewritten.replace("however,", "")
    if section_confidence is not None and section_confidence < 0.4:
        if not any(marker in rewritten.lower() for marker in LOW_CONFIDENCE_HEDGES):
            rewritten = "The available evidence suggests " + rewritten[0].lower() + rewritten[1:]
    return rewritten.strip()


def _removed_required_hedging(original: str, rewritten: str) -> bool:
    original_lower = original.lower()
    rewritten_lower = rewritten.lower()
    original_has_hedge = any(marker in original_lower for marker in LOW_CONFIDENCE_HEDGES)
    rewritten_has_hedge = any(marker in rewritten_lower for marker in LOW_CONFIDENCE_HEDGES)
    return original_has_hedge and not rewritten_has_hedge
