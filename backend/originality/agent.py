"""Originality runtime plus the guarded ADK-facing entrypoint.

The runtime is independent from ADK so the current in-process pipeline,
future LangGraph nodes, and tests all use the same compliance stack.
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
from models.generation import GeneratedPaper
from originality.classifier import classify_section_findings
from originality.config import OriginalityConfig
from originality.scanner import scan_sections
from originality.schemas import (
    OriginalityAgentError,
    OriginalityAgentResult,
    OriginalityDecision,
    OriginalityPaperReport,
    SectionOriginalityReport,
)
from originality.utils import (
    SECTION_ORDER,
    build_section_ai_scores,
    build_section_map,
    normalize_whitespace,
    summarize_status_counts,
)

logger = logging.getLogger("papereasy.backend.originality.agent")

try:  # pragma: no cover - environment dependent import
    from google import genai as _google_genai  # noqa: F401
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
class OriginalityRuntime:
    settings: Settings
    config: OriginalityConfig


async def run_originality_pipeline(
    *,
    paper_snapshot: object,
    humanized_draft: object | None = None,
    humanizer_ai_score: float | None = None,
    humanizer_graph_action: str | None = None,
    citation_draft: object | None = None,
    author_metadata: object | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: OriginalityConfig | None = None,
    winston_client=None,
    copyleaks_client=None,
    logger_: logging.Logger | None = None,
) -> OriginalityAgentResult:
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or OriginalityConfig.from_settings(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())

    if paper_snapshot in (None, "", {}):
        return _build_error_result(
            code="missing_humanized_snapshot",
            message="The originality agent requires a humanized paper snapshot.",
            trace_id=resolved_trace_id,
            details={},
        )

    try:
        parsed_snapshot = GeneratedPaper.model_validate(paper_snapshot)
    except ValidationError as exc:
        return _build_error_result(
            code="invalid_humanized_snapshot",
            message="The humanized paper snapshot is malformed and could not be parsed.",
            trace_id=resolved_trace_id,
            details={"validation_errors": exc.errors()},
        )

    section_texts = build_section_map(
        humanized_draft=humanized_draft,
        paper_snapshot=parsed_snapshot,
    )
    if not any(text.strip() for text in section_texts.values()):
        return _build_error_result(
            code="missing_section_text",
            message="The originality agent requires non-empty section text from the humanizer output.",
            trace_id=resolved_trace_id,
            details={},
        )

    active_logger.info("Originality trace %s started for paper '%s'.", resolved_trace_id, parsed_snapshot.paper.title[:80])

    section_ai_scores = build_section_ai_scores(humanized_draft)
    if humanizer_ai_score is None and humanized_draft not in (None, "", {}):
        try:
            from humanizer.schemas import HumanizedPaperDraft

            parsed_humanized = HumanizedPaperDraft.model_validate(humanized_draft)
            humanizer_ai_score = parsed_humanized.global_ai_pattern_score_after
        except Exception:
            humanizer_ai_score = None

    reference_lines = list(parsed_snapshot.paper.references)
    reference_lines.extend(_extract_reference_titles(citation_draft))

    section_scans, scan_metadata = await scan_sections(
        section_texts=section_texts,
        config=resolved_config,
        settings=resolved_settings,
        trace_id=resolved_trace_id,
        winston_client=winston_client,
        copyleaks_client=copyleaks_client,
        logger_=active_logger,
    )

    reports: dict[str, SectionOriginalityReport] = {}
    originality_scores: list[float] = []
    ai_scores: list[float] = []
    blocking_issue_found = False
    manual_review_found = False

    for section_name in SECTION_ORDER:
        scan = section_scans.get(section_name)
        section_text = section_texts.get(section_name, "")
        provider_failures = list((scan.metadata if scan else {}).get("provider_failures", []))
        if scan is None:
            reports[section_name] = SectionOriginalityReport(
                section_name=section_name,
                status="provider_review_required",
                requires_manual_review=True,
                summary=["No provider scan data was available for this section."],
            )
            manual_review_found = True
            continue

        classified_spans = classify_section_findings(
            section_name=section_name,
            section_text=section_text,
            findings=scan.spans,
            reference_lines=reference_lines,
            author_metadata=author_metadata,
            config=resolved_config,
        )
        section_status, requires_manual_review, summary = _build_section_status(
            section_name=section_name,
            spans=classified_spans,
            provider_failures=provider_failures,
        )
        if section_status in {"blocked", "needs_manual_review", "provider_review_required"}:
            manual_review_found = True
        if any(span.classification == "likely_unattributed_copying" for span in classified_spans):
            blocking_issue_found = True
        section_originality_score = scan.originality_score
        if section_originality_score is None:
            section_originality_score = round(
                max(0.0, 1.0 - max((span.severity for span in classified_spans), default=0.0)),
                4,
            )
        originality_scores.append(section_originality_score)
        section_ai_score = section_ai_scores.get(section_name, scan.ai_score)
        if section_ai_score is not None:
            ai_scores.append(section_ai_score)
        reports[section_name] = SectionOriginalityReport(
            section_name=section_name,
            originality_score=section_originality_score,
            ai_score=section_ai_score,
            spans=classified_spans,
            status=section_status,
            requires_manual_review=requires_manual_review,
            summary=summary,
        )

    global_originality_score = round(mean(originality_scores), 4) if originality_scores else None
    global_ai_score = (
        float(humanizer_ai_score)
        if humanizer_ai_score is not None
        else (round(mean(ai_scores), 4) if ai_scores else None)
    )
    decision = _build_decision(
        reports=reports,
        global_ai_score=global_ai_score,
        humanizer_graph_action=humanizer_graph_action,
        blocking_issue_found=blocking_issue_found,
        manual_review_found=manual_review_found,
        config=resolved_config,
    )
    report = OriginalityPaperReport(
        sections=reports,
        global_originality_score=global_originality_score,
        global_ai_score=global_ai_score,
        decision=decision,
        metadata={
            "trace_id": resolved_trace_id,
            "provider_summary": scan_metadata.get("provider_summary", {}),
            "provider_failures": scan_metadata.get("provider_failures", {}),
            "section_status_counts": summarize_status_counts(report.status for report in reports.values()),
        },
    )
    return OriginalityAgentResult(
        approved_snapshot=parsed_snapshot if decision.approved else None,
        originality_report=report,
        trace_id=resolved_trace_id,
        metadata={
            "provider_used": _select_provider_used(scan_metadata.get("provider_summary", {})),
            "section_status_counts": report.metadata.get("section_status_counts", {}),
            "decision": decision.graph_action,
        },
    )


if ADKBaseAgent is not None:

    class OriginalityAgent(ADKBaseAgent):
        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: OriginalityConfig = Field(default_factory=OriginalityConfig.from_settings, exclude=True)

        def __init__(self, *, settings: Settings | None = None, config: OriginalityConfig | None = None):
            resolved_settings = settings or get_settings()
            resolved_config = config or OriginalityConfig.from_settings(resolved_settings)
            super().__init__(
                name="originality_agent",
                description="Runs final originality, attribution, and compliance checks using Winston AI with Copyleaks fallback.",
                settings=resolved_settings,
                config=resolved_config,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_originality_pipeline(
                paper_snapshot=state.get("paper_snapshot"),
                humanized_draft=state.get("humanized_draft"),
                humanizer_ai_score=_coerce_optional_float(state.get("humanizer_ai_score")),
                humanizer_graph_action=_coerce_optional_text(state.get("humanizer_graph_action")),
                citation_draft=state.get("citation_draft"),
                author_metadata=state.get("author_metadata"),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
            )

            if result.approved_snapshot is not None:
                state["approved_snapshot"] = result.approved_snapshot.model_dump(mode="python")
            if result.originality_report is not None:
                state["originality_report"] = result.originality_report.model_dump(mode="python")
            if result.error is not None:
                state["originality_error"] = result.error.model_dump(mode="python")

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

    class OriginalityAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


def build_runtime(settings: Settings | None = None, config: OriginalityConfig | None = None) -> OriginalityRuntime:
    resolved_settings = settings or get_settings()
    resolved_config = config or OriginalityConfig.from_settings(resolved_settings)
    return OriginalityRuntime(settings=resolved_settings, config=resolved_config)


def _build_error_result(
    *,
    code: str,
    message: str,
    trace_id: str,
    details: dict[str, Any],
) -> OriginalityAgentResult:
    return OriginalityAgentResult(
        error=OriginalityAgentError(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details,
        ),
        trace_id=trace_id,
        metadata={"status": "error"},
    )


def _extract_reference_titles(citation_draft: object | None) -> list[str]:
    if citation_draft in (None, "", {}):
        return []
    bibliography = []
    if isinstance(citation_draft, dict):
        bibliography = citation_draft.get("bibliography") or []
    elif hasattr(citation_draft, "bibliography"):
        bibliography = getattr(citation_draft, "bibliography")
    references: list[str] = []
    for item in bibliography:
        if isinstance(item, dict):
            title = normalize_whitespace(item.get("ieee_reference") or item.get("title"))
        else:
            title = normalize_whitespace(getattr(item, "ieee_reference", None) or getattr(item, "title", None))
        if title:
            references.append(title)
    return references


def _build_section_status(
    *,
    section_name: str,
    spans,
    provider_failures: list[dict[str, str]],
) -> tuple[str, bool, list[str]]:
    if provider_failures and not spans:
        return (
            "provider_review_required",
            True,
            [f"Originality providers did not return a completed scan for {section_name}."],
        )
    if not spans:
        return ("clean", False, ["No blocking overlap was detected in this section."])

    classifications = {span.classification for span in spans}
    if "likely_unattributed_copying" in classifications:
        return (
            "blocked",
            True,
            ["High-severity unattributed overlap requires manual review before approval."],
        )
    if classifications & {"possible_self_overlap", "manual_review_required", "uncited_close_paraphrase"}:
        return (
            "needs_manual_review",
            True,
            ["Attribution-sensitive overlap was detected and should be reviewed manually."],
        )
    return (
        "clean_with_notes",
        False,
        ["Only acceptable quoted, cited, or boilerplate overlap was detected."],
    )


def _build_decision(
    *,
    reports: dict[str, SectionOriginalityReport],
    global_ai_score: float | None,
    humanizer_graph_action: str | None,
    blocking_issue_found: bool,
    manual_review_found: bool,
    config: OriginalityConfig,
) -> OriginalityDecision:
    if blocking_issue_found or manual_review_found:
        return OriginalityDecision(
            graph_action="needs_manual_review",
            approved=False,
            reason_codes=["originality_manual_review_required"],
            summary="The manuscript requires manual originality review before approval.",
        )
    if (global_ai_score is not None and global_ai_score >= config.retry_humanizer_ai_threshold) or (
        normalize_whitespace(humanizer_graph_action) == "retry_humanizer"
    ):
        return OriginalityDecision(
            graph_action="retry_humanizer",
            approved=False,
            reason_codes=["ai_style_score_high"],
            summary="Originality checks passed, but the AI-style score still requires another humanizer pass.",
        )
    return OriginalityDecision(
        graph_action="accept",
        approved=True,
        reason_codes=["originality_passed"],
        summary="The manuscript passed the final originality and compliance gate.",
    )


def _select_provider_used(provider_summary: dict[str, int]) -> str | None:
    if not provider_summary:
        return None
    return sorted(provider_summary.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _coerce_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _coerce_optional_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


runtime = build_runtime()
if ADKBaseAgent is not None:  # pragma: no branch
    agent = OriginalityAgent(settings=runtime.settings, config=runtime.config)

    try:  # pragma: no cover - optional A2A runtime wiring
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("ADK A2A bridge is unavailable: %s", exc)
        to_a2a = None

    if to_a2a is not None:  # pragma: no cover - environment dependent
        try:
            app = to_a2a(agent, public_url=os.environ.get("PUBLIC_URL"))
        except Exception as exc:
            logger.warning("Unable to build A2A app for the originality agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the originality agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
