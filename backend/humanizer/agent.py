"""Humanizer runtime plus the guarded ADK-facing entrypoint.

The runtime is intentionally independent from ADK so the current in-process
pipeline, future LangGraph nodes, and tests can all reuse the same logic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from statistics import mean
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationError

from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from humanizer.config import HumanizerConfig
from humanizer.rewriter import HybridSectionRewriter
from humanizer.perplexity import PerplexityScorer
from humanizer.schemas import (
    HumanizedPaperDraft,
    HumanizedSection,
    HumanizerAgentError,
    HumanizerAgentResult,
    ParagraphHumanizationReport,
    SectionHumanizationReport,
)
from humanizer.utils import (
    SECTION_ORDER,
    build_diff_summary,
    build_generated_paper,
    build_section_text_map,
)
from models.generation import GeneratedPaper, ResearchPaperSchema

logger = logging.getLogger("papereasy.backend.humanizer.agent")

try:  # pragma: no cover - environment dependent import
    from google.adk.agents import BaseAgent as ADKBaseAgent
    from google.adk.events import Event
    from google.genai import types

    ADK_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - environment dependent
    ADKBaseAgent = None
    Event = None
    types = None
    ADK_IMPORT_ERROR = exc


@dataclass(frozen=True)
class HumanizerRuntime:
    settings: Settings
    config: HumanizerConfig
    vertex_client: VertexGeminiClient


async def run_humanizer_pipeline(
    *,
    paper: object,
    formatted_text: str | None = None,
    latex_ready: str | None = None,
    written_draft: object | None = None,
    section_confidences: dict[str, float] | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: HumanizerConfig | None = None,
    vertex_client: VertexGeminiClient | None = None,
    logger_: logging.Logger | None = None,
) -> HumanizerAgentResult:
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or HumanizerConfig.from_settings(resolved_settings)
    resolved_vertex_client = vertex_client or VertexGeminiClient(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())

    if paper in (None, "", {}):
        return _build_error_result(
            code="missing_formatted_paper",
            message="The humanizer agent requires formatter output with a paper snapshot.",
            trace_id=resolved_trace_id,
            details={},
        )

    try:
        parsed_paper = ResearchPaperSchema.model_validate(paper)
    except ValidationError as exc:
        return _build_error_result(
            code="invalid_formatted_paper",
            message="The formatter paper snapshot is malformed and could not be parsed.",
            trace_id=resolved_trace_id,
            details={"validation_errors": exc.errors()},
        )

    if not (formatted_text or "").strip():
        formatted_text = build_generated_paper(source_paper=parsed_paper, section_texts=build_section_text_map(parsed_paper)).formatted_text
    if not (latex_ready or "").strip():
        latex_ready = build_generated_paper(source_paper=parsed_paper, section_texts=build_section_text_map(parsed_paper)).latex_ready

    if not formatted_text.strip():
        return _build_error_result(
            code="missing_formatted_text",
            message="The humanizer agent requires non-empty formatted text.",
            trace_id=resolved_trace_id,
            details={},
        )

    active_logger.info("Humanizer trace %s started for paper '%s'.", resolved_trace_id, parsed_paper.title[:80])

    section_texts = build_section_text_map(parsed_paper)
    confidence_map = _normalize_section_confidences(section_confidences)
    if written_draft not in (None, "", {}):
        confidence_map = _merge_confidences_from_written_draft(
            written_draft=written_draft,
            existing=confidence_map,
            logger_=active_logger,
        )

    perplexity_scorer = PerplexityScorer(resolved_config)
    rewriter = HybridSectionRewriter(
        config=resolved_config,
        vertex_client=resolved_vertex_client if resolved_config.use_model_rewriter else None,
        perplexity_scorer=perplexity_scorer,
    )

    humanized_sections: dict[str, HumanizedSection] = {}
    ai_before_scores: list[float] = []
    ai_after_scores: list[float] = []
    perplexity_before_scores: list[float] = []
    perplexity_after_scores: list[float] = []
    total_iterations = 0

    for section_name in SECTION_ORDER:
        original_text = section_texts[section_name]
        outcome = await rewriter.humanize_section(
            section_name=section_name,
            text=original_text,
            section_confidence=confidence_map.get(section_name),
            trace_id=resolved_trace_id,
            logger_=active_logger,
        )
        ai_before_scores.append(outcome.analysis_before.ai_pattern_score)
        ai_after_scores.append(outcome.analysis_after.ai_pattern_score)
        if outcome.section_perplexity_before.available:
            perplexity_before_scores.append(outcome.section_perplexity_before.value)
        if outcome.section_perplexity_after.available:
            perplexity_after_scores.append(outcome.section_perplexity_after.value)
        total_iterations += outcome.iterations

        paragraph_reports = _build_paragraph_reports(outcome)
        passed_threshold = outcome.analysis_after.ai_pattern_score <= resolved_config.ai_pattern_threshold
        needs_writer_loopback = outcome.analysis_after.ai_pattern_score >= resolved_config.writer_loopback_threshold
        needs_graph_retry = not passed_threshold and not needs_writer_loopback

        report = SectionHumanizationReport(
            section_name=section_name,
            original_text=original_text,
            final_text=outcome.text,
            original_perplexity=outcome.section_perplexity_before.value if outcome.section_perplexity_before.available else 0.0,
            final_perplexity=outcome.section_perplexity_after.value if outcome.section_perplexity_after.available else 0.0,
            detected_patterns=outcome.analysis_after.detected_patterns,
            paragraph_reports=paragraph_reports,
            rewrite_iterations=outcome.iterations,
            passed_threshold=passed_threshold,
            needs_graph_retry=needs_graph_retry,
            needs_writer_loopback=needs_writer_loopback,
        )
        humanized_sections[section_name] = HumanizedSection(
            section_name=section_name,
            text=outcome.text,
            diff_summary=build_diff_summary(original_text, outcome.text),
            report=report,
        )

    final_section_texts = {
        section_name: section.text
        for section_name, section in humanized_sections.items()
    }
    paper_snapshot = build_generated_paper(source_paper=parsed_paper, section_texts=final_section_texts)
    graph_action = _select_graph_action(
        sections=humanized_sections,
        config=resolved_config,
    )
    humanized_draft = HumanizedPaperDraft(
        sections=humanized_sections,
        global_ai_pattern_score_before=round(mean(ai_before_scores), 4) if ai_before_scores else 0.0,
        global_ai_pattern_score_after=round(mean(ai_after_scores), 4) if ai_after_scores else 0.0,
        global_perplexity_before=round(mean(perplexity_before_scores), 4) if perplexity_before_scores else 0.0,
        global_perplexity_after=round(mean(perplexity_after_scores), 4) if perplexity_after_scores else 0.0,
        passed_threshold=graph_action == "accept",
        graph_action=graph_action,
        metadata={
            "trace_id": resolved_trace_id,
            "iteration_count": total_iterations,
            "formatted_text_length": len(formatted_text),
            "latex_ready_length": len(latex_ready or ""),
            "perplexity_available": bool(perplexity_before_scores or perplexity_after_scores),
        },
    )
    return HumanizerAgentResult(
        humanized_draft=humanized_draft,
        paper_snapshot=paper_snapshot,
        trace_id=resolved_trace_id,
        metadata={
            "graph_action": graph_action,
            "iteration_count": total_iterations,
        },
    )


if ADKBaseAgent is not None:

    class HumanizerAgent(ADKBaseAgent):
        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: HumanizerConfig = Field(default_factory=HumanizerConfig.from_settings, exclude=True)
        vertex_client: VertexGeminiClient | None = Field(default=None, exclude=True)

        def __init__(
            self,
            *,
            settings: Settings | None = None,
            config: HumanizerConfig | None = None,
            vertex_client: VertexGeminiClient | None = None,
        ):
            resolved_settings = settings or get_settings()
            resolved_config = config or HumanizerConfig.from_settings(resolved_settings)
            resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
            super().__init__(
                name="humanizer_agent",
                description="Reduces AI-writing signals in formatted IEEE paper text while preserving meaning, citations, LaTeX safety, and section intent.",
                settings=resolved_settings,
                config=resolved_config,
                vertex_client=resolved_client,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_humanizer_pipeline(
                paper=state.get("paper"),
                formatted_text=_coerce_optional_text(state.get("formatted_text")),
                latex_ready=_coerce_optional_text(state.get("latex_ready")),
                written_draft=state.get("written_draft"),
                section_confidences=state.get("section_confidences"),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
                vertex_client=self.vertex_client,
            )

            if result.humanized_draft is not None:
                state["humanized_draft"] = result.humanized_draft.model_dump(mode="python")
            if result.paper_snapshot is not None:
                state["humanized_paper_snapshot"] = result.paper_snapshot.model_dump(mode="python")
            if result.error is not None:
                state["humanizer_error"] = result.error.model_dump(mode="python")

            yield Event(
                invocationId=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                turnComplete=True,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=result.model_dump_json(indent=2))],
                ),
            )

else:

    class HumanizerAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


def build_runtime(
    settings: Settings | None = None,
    config: HumanizerConfig | None = None,
    vertex_client: VertexGeminiClient | None = None,
) -> HumanizerRuntime:
    resolved_settings = settings or get_settings()
    resolved_config = config or HumanizerConfig.from_settings(resolved_settings)
    resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
    return HumanizerRuntime(
        settings=resolved_settings,
        config=resolved_config,
        vertex_client=resolved_client,
    )


def _build_error_result(
    *,
    code: str,
    message: str,
    trace_id: str,
    details: dict[str, Any],
) -> HumanizerAgentResult:
    return HumanizerAgentResult(
        error=HumanizerAgentError(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details,
        ),
        trace_id=trace_id,
        metadata={"status": "error"},
    )


def _normalize_section_confidences(value: dict[str, float] | None) -> dict[str, float]:
    if not value:
        return {}
    normalized: dict[str, float] = {}
    for key, score in value.items():
        try:
            bounded = float(score)
        except (TypeError, ValueError):
            continue
        if 0.0 <= bounded <= 1.0:
            normalized[str(key)] = bounded
    return normalized


def _merge_confidences_from_written_draft(
    *,
    written_draft: object,
    existing: dict[str, float],
    logger_: logging.Logger,
) -> dict[str, float]:
    merged = dict(existing)
    try:
        from writing.schemas import WrittenPaperDraft

        parsed = WrittenPaperDraft.model_validate(written_draft)
    except Exception as exc:
        logger_.warning("Humanizer could not parse written_draft for confidence hints: %s", exc)
        return merged

    merged.setdefault("abstract", parsed.abstract.confidence)
    for section_name, section in parsed.sections.items():
        merged.setdefault(section_name, section.confidence)
    return merged


def _build_paragraph_reports(outcome) -> list[ParagraphHumanizationReport]:
    reports: list[ParagraphHumanizationReport] = []
    before_lookup = {metric_idx: metric for metric_idx, metric in enumerate(outcome.paragraph_perplexities_before)}
    after_lookup = {metric_idx: metric for metric_idx, metric in enumerate(outcome.paragraph_perplexities_after)}
    for paragraph in outcome.analysis_after.paragraphs:
        before_analysis = next(
            (item for item in outcome.analysis_before.paragraphs if item.paragraph_index == paragraph.paragraph_index),
            paragraph,
        )
        before_metric = before_lookup.get(paragraph.paragraph_index)
        after_metric = after_lookup.get(paragraph.paragraph_index)
        reports.append(
            ParagraphHumanizationReport(
                paragraph_index=paragraph.paragraph_index,
                original_perplexity=before_metric.value if before_metric and before_metric.available else 0.0,
                final_perplexity=after_metric.value if after_metric and after_metric.available else 0.0,
                cadence_score_before=before_analysis.cadence_score,
                cadence_score_after=paragraph.cadence_score,
                ai_pattern_score_before=before_analysis.ai_pattern_score,
                ai_pattern_score_after=paragraph.ai_pattern_score,
                rewrites_applied=list(outcome.applied_changes),
            )
        )
    return reports


def _select_graph_action(
    *,
    sections: dict[str, HumanizedSection],
    config: HumanizerConfig,
) -> str:
    if any(section.report.needs_writer_loopback for section in sections.values()):
        return "loopback_writing"
    if any(section.report.needs_graph_retry for section in sections.values()):
        return "retry_humanizer"
    return "accept"


def _coerce_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


runtime = build_runtime()
if ADKBaseAgent is not None:  # pragma: no branch
    agent = HumanizerAgent(
        settings=runtime.settings,
        config=runtime.config,
        vertex_client=runtime.vertex_client,
    )

    try:  # pragma: no cover - optional A2A runtime wiring
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("ADK A2A bridge is unavailable: %s", exc)
        to_a2a = None

    if to_a2a is not None:  # pragma: no cover - environment dependent
        try:
            app = to_a2a(agent, public_url=os.environ.get("PUBLIC_URL"))
        except Exception as exc:
            logger.warning("Unable to build A2A app for the humanizer agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the humanizer agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
