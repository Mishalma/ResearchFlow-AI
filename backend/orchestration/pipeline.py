from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from agents.citation_agent import CitationAgent
from agents.figure_table_agent import FigureTableAgent
from agents.humanizer_agent import HumanizerAgent
from agents.ieee_formatting_agent import IEEEFormattingAgent
from agents.originality_agent import OriginalityAgent
from agents.registry import get_agent_registry
from agents.structuring_agent import StructuringAgent
from agents.writing_agent import WritingAgent
from app.services.paper_service import validate_research_paper
from core.config import Settings, get_settings
from core.exceptions import (
    AgentExecutionError,
    InvalidAgentResponseError,
    OriginalityReviewBlockedError,
    PaperValidationError,
)
from core.vertex_client import VertexGeminiClient
from humanizer.config import MAX_ITERATIONS
from humanizer.utils import build_section_text_map
from mcp.mcp_server import build_default_mcp_server
from models.generation import (
    AgentTiming,
    CitationAgentOutput,
    FigureTableAgentOutput,
    FormattingAgentOutput,
    GeneratedPaper,
    GenerationMetadata,
    HumanizerAgentOutput,
    OriginalityAgentOutput,
    PipelineResult,
    ResearchPaperSchema,
    StructuringAgentOutput,
    WritingAgentOutput,
)
from orchestration.a2a_manager import A2AManager, InProcessTransport

logger = logging.getLogger("papereasy.backend.pipeline")
MAX_HUMANIZER_RETRIES = MAX_ITERATIONS


def _paper_summary(paper: ResearchPaperSchema) -> str:
    completed_sections = [
        key
        for key in (
            "introduction",
            "related_work",
            "methodology",
            "results",
            "discussion",
            "limitations",
            "conclusion",
        )
        if getattr(paper.sections, key).strip()
    ]
    return (
        f"title='{paper.title[:80]}', keywords={len(paper.keywords)}, "
        f"references={len(paper.references)}, sections={completed_sections}"
    )


def _extract_agent_error_details(error_payload: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(error_payload, dict):
        return {}

    details_payload = error_payload.get("details")
    details = dict(details_payload) if isinstance(details_payload, dict) else {}

    for key in ("code", "trace_id"):
        value = error_payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                details.setdefault(key, normalized)

    return details


def _raise_agent_runtime_error(
    *,
    agent_name: str,
    error_payload: dict[str, object] | None,
    default_message: str,
) -> None:
    message = default_message
    if isinstance(error_payload, dict):
        candidate_message = error_payload.get("message")
        if isinstance(candidate_message, str):
            normalized_message = candidate_message.strip()
            if normalized_message:
                message = normalized_message

    details = _extract_agent_error_details(error_payload)
    if details:
        logger.warning("Agent %s failed with details: %s", agent_name, details)

    raise AgentExecutionError(
        agent_name,
        message=message,
        details=details or None,
    )


async def _dispatch_validated_stage(
    *,
    a2a_manager: A2AManager,
    sender: str,
    recipient: str,
    task: str,
    trace_id: str,
    payload: dict[str, object],
    response_model,
    require_references: bool,
    validation_events: list[str],
):
    retry_payload = dict(payload)

    for validation_attempt in range(1, 3):
        result = await a2a_manager.dispatch(
            sender=sender,
            recipient=recipient,
            task=task,
            trace_id=trace_id,
            payload=retry_payload,
        )

        try:
            structured_result = response_model.model_validate(result.payload)
        except ValidationError as exc:
            issues = [error.get("msg", "invalid structured response") for error in exc.errors()]
            logger.warning(
                "Agent %s returned schema-invalid payload on validation attempt %s for trace %s: %s",
                recipient,
                validation_attempt,
                trace_id,
                "; ".join(issues),
            )
            validation_events.append(
                f"{recipient}: schema validation failed on attempt {validation_attempt} - {'; '.join(issues)}"
            )
            if validation_attempt == 1:
                retry_payload = dict(payload)
                retry_payload["validation_feedback"] = issues
                continue
            raise InvalidAgentResponseError(recipient) from exc

        if isinstance(structured_result, OriginalityAgentOutput):
            if structured_result.approved_snapshot is None:
                validation_events.append(
                    f"{recipient}: originality decision '{structured_result.decision_graph_action or 'unknown'}' returned without approved snapshot"
                )
                return structured_result, result
            paper = structured_result.approved_snapshot.paper
        else:
            paper = structured_result if isinstance(structured_result, ResearchPaperSchema) else structured_result.paper
        issues = validate_research_paper(paper, require_references=require_references)

        if isinstance(structured_result, (FormattingAgentOutput, HumanizerAgentOutput)):
            if not structured_result.formatted_text.strip():
                issues.append("formatted_text is empty")
            if not structured_result.latex_ready.strip():
                issues.append("latex_ready is empty")
        elif isinstance(structured_result, OriginalityAgentOutput):
            approved_snapshot = structured_result.approved_snapshot
            if approved_snapshot is None:
                issues.append("approved_snapshot is empty")
            else:
                if not approved_snapshot.formatted_text.strip():
                    issues.append("approved_snapshot.formatted_text is empty")
                if not approved_snapshot.latex_ready.strip():
                    issues.append("approved_snapshot.latex_ready is empty")

        logger.info(
            "Agent %s output summary for trace %s: %s",
            recipient,
            trace_id,
            _paper_summary(paper),
        )

        if not issues:
            validation_events.append(
                f"{recipient}: validation passed on attempt {validation_attempt}"
            )
            return structured_result, result

        logger.warning(
            "Agent %s returned invalid paper on validation attempt %s for trace %s: %s",
            recipient,
            validation_attempt,
            trace_id,
            "; ".join(issues),
        )
        validation_events.append(
            f"{recipient}: validation failed on attempt {validation_attempt} - {'; '.join(issues)}"
        )

        if validation_attempt == 1:
            retry_payload = dict(payload)
            retry_payload["validation_feedback"] = issues
            continue

        raise PaperValidationError(recipient, issues)

    raise PaperValidationError(recipient, ["unknown validation failure"])


async def _dispatch_figure_table_stage(
    *,
    a2a_manager: A2AManager,
    figure_table_agent: FigureTableAgent,
    writing_output: WritingAgentOutput,
    project_id: str,
    trace_id: str,
    pipeline_context: dict[str, object],
) -> tuple[FigureTableAgentOutput, float]:
    """Run the non-blocking figure/table stage and preserve pipeline continuity on failure."""

    try:
        dispatch_result = await a2a_manager.dispatch(
            sender="pipeline",
            recipient=figure_table_agent.agent_name,
            task="extract_figure_table_assets",
            trace_id=trace_id,
            payload={
                "paper": writing_output.model_dump(mode="python"),
                "project_id": project_id,
            },
        )
        output = FigureTableAgentOutput.model_validate(dispatch_result.payload)
        if output.figures is not None:
            pipeline_context["generated_figures"] = output.figures
        if output.tables is not None:
            pipeline_context["generated_tables"] = output.tables
        pipeline_context["generated_figure_count"] = output.figure_count
        pipeline_context["generated_table_count"] = output.table_count
        pipeline_context["figure_table_status"] = output.status
        pipeline_context["figure_table_error"] = output.error
        return output, dispatch_result.duration_ms
    except Exception as exc:
        logger.warning(
            "figure_table_agent failed (non-blocking); preserving existing generated visuals: %s",
            exc,
        )
        output = FigureTableAgentOutput(
            figures=None,
            tables=None,
            enriched_draft="",
            figure_count=0,
            table_count=0,
            extraction_metadata={"error": str(exc)},
            status="failed",
            error=str(exc),
        )
        pipeline_context["generated_figure_count"] = 0
        pipeline_context["generated_table_count"] = 0
        pipeline_context["figure_table_status"] = "failed"
        pipeline_context["figure_table_error"] = str(exc)
        return output, 0.0


def _merge_writing_with_figures(
    *,
    writing_output: WritingAgentOutput,
    figure_table_output: FigureTableAgentOutput,
) -> WritingAgentOutput:
    """Merge enriched figure references into the writing output while preserving its shape."""

    if not figure_table_output.enriched_written_draft:
        return writing_output

    merged = writing_output.model_copy(deep=True)
    merged.written_draft = figure_table_output.enriched_written_draft

    enriched_draft = figure_table_output.enriched_written_draft
    abstract_section = enriched_draft.get("abstract") or {}
    body_sections = enriched_draft.get("sections") or {}
    if isinstance(abstract_section, dict):
        merged.abstract = str(abstract_section.get("text", merged.abstract)).strip() or merged.abstract
    for section_name in (
        "introduction",
        "related_work",
        "methodology",
        "results",
        "discussion",
        "limitations",
        "conclusion",
    ):
        section_payload = body_sections.get(section_name) or {}
        if isinstance(section_payload, dict):
            section_text = str(section_payload.get("text", getattr(merged.sections, section_name))).strip()
            if section_text:
                setattr(merged.sections, section_name, section_text)
    return merged


def _build_formatting_visual_payload(
    output: FigureTableAgentOutput,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, list[dict[str, object]]]]:
    figures: dict[str, list[dict[str, object]]] = {}
    tables: dict[str, list[dict[str, object]]] = {}

    for entry in output.figures or []:
        if not entry.render_success:
            continue
        asset_path = (
            output.extraction_metadata.get("asset_paths", {}).get(entry.spec.id)
            if isinstance(output.extraction_metadata, dict)
            else None
        )
        figures.setdefault(entry.spec.section, []).append(
            {
                "id": entry.spec.id,
                "caption": entry.spec.caption,
                "label": entry.spec.id,
                "path": f"figures/{entry.spec.id}.png",
                "latex_block": entry.latex_block,
                "png_base64": entry.png_base64,
                "svg_content": entry.svg_content,
                "asset_path": asset_path,
                "placement_hint": entry.spec.placement_hint,
                "spec": entry.spec.model_dump(mode="python"),
            }
        )

    for entry in output.tables or []:
        if not entry.render_success:
            continue
        tables.setdefault(entry.spec.section, []).append(
            {
                "id": entry.spec.id,
                "caption": entry.spec.caption,
                "label": entry.spec.id,
                "latex": entry.latex_table or entry.latex_block,
                "latex_block": entry.latex_block,
                "placement_hint": entry.spec.placement_hint,
                "spec": entry.spec.model_dump(mode="python"),
            }
        )

    return figures, tables


def _execute_humanizer_loop(
    *,
    humanizer_agent: HumanizerAgent,
    paper: ResearchPaperSchema,
    trace_id: str,
    pipeline_context: dict[str, object],
) -> HumanizerAgentOutput:
    result = humanizer_agent.run(
        build_section_text_map(paper),
        paper=paper,
        iteration=0,
    )

    for attempt in range(1, MAX_HUMANIZER_RETRIES + 1):
        action = str(result.get("graph_action") or "accept")
        logger.info(
            "[Humanizer] attempt=%s action=%s composite_after=%s",
            attempt,
            action,
            result.get("scores_after", {}).get("composite_score", "?"),
        )

        if action == "accept":
            logger.info("[Humanizer] accepted after %s attempt(s)", attempt)
            break

        if action == "retry_humanizer":
            result = humanizer_agent.run(
                result["updated_sections"],
                paper=paper,
                iteration=attempt,
            )
            continue

        if action == "loopback_writing":
            logger.warning(
                "[Humanizer] loopback_writing triggered - signalling writing agent",
            )
            pipeline_context["humanizer_loopback"] = True
            pipeline_context["humanizer_feedback"] = result.get("scores_after", {})
            break

    else:
        logger.warning(
            "[Humanizer] max retries (%s) reached, proceeding with best result",
            MAX_HUMANIZER_RETRIES,
        )

    output = humanizer_agent.build_output(
        paper=paper,
        runtime_result=result,
        trace_id=trace_id,
    )
    return HumanizerAgentOutput.model_validate(output)


async def run_pipeline(
    text: str,
    settings: Settings | None = None,
    *,
    project_id: str = "",
) -> PipelineResult:
    resolved_settings = settings or get_settings()
    trace_id = str(uuid4())
    start_time = perf_counter()
    validation_events: list[str] = []
    pipeline_context: dict[str, object] = {}

    vertex_client = VertexGeminiClient(resolved_settings)
    mcp_server = build_default_mcp_server()
    registry = get_agent_registry(resolved_settings)
    a2a_manager = A2AManager(resolved_settings, transport=InProcessTransport())

    structuring_agent = StructuringAgent(
        vertex_client,
        registry.get("structuring_agent"),
        resolved_settings,
    )
    writing_agent = WritingAgent(vertex_client, registry.get("writing_agent"))
    figure_table_agent = FigureTableAgent(
        vertex_client,
        registry.get("figure_table_agent"),
        mcp_server,
    )
    citation_agent = CitationAgent(
        mcp_server,
        registry.get("citation_agent"),
        resolved_settings,
    )
    formatting_agent = IEEEFormattingAgent(registry.get("ieee_formatting_agent"))
    humanizer_agent = HumanizerAgent(vertex_client, registry.get("humanizer_agent"))
    originality_agent = OriginalityAgent(registry.get("originality_agent"))

    for agent in [
        structuring_agent,
        writing_agent,
        figure_table_agent,
        citation_agent,
        formatting_agent,
        humanizer_agent,
        originality_agent,
    ]:
        a2a_manager.register(agent)

    logger.info("Pipeline trace %s started with %s source characters", trace_id, len(text))

    structuring_result, structuring_dispatch = await _dispatch_validated_stage(
        a2a_manager=a2a_manager,
        sender="pipeline",
        recipient=structuring_agent.agent_name,
        task="structure_document",
        trace_id=trace_id,
        payload={"raw_text": text},
        response_model=StructuringAgentOutput,
        require_references=False,
        validation_events=validation_events,
    )

    writing_result, writing_dispatch = await _dispatch_validated_stage(
        a2a_manager=a2a_manager,
        sender=structuring_agent.agent_name,
        recipient=writing_agent.agent_name,
        task="improve_sections",
        trace_id=trace_id,
        payload={"paper": structuring_result.model_dump()},
        response_model=WritingAgentOutput,
        require_references=False,
        validation_events=validation_events,
    )

    figure_table_result, figure_table_duration_ms = await _dispatch_figure_table_stage(
        a2a_manager=a2a_manager,
        figure_table_agent=figure_table_agent,
        writing_output=writing_result,
        project_id=project_id,
        trace_id=trace_id,
        pipeline_context=pipeline_context,
    )
    merged_writing_result = _merge_writing_with_figures(
        writing_output=writing_result,
        figure_table_output=figure_table_result,
    )
    formatting_figures, formatting_tables = _build_formatting_visual_payload(figure_table_result)

    citation_result, citation_dispatch = await _dispatch_validated_stage(
        a2a_manager=a2a_manager,
        sender=figure_table_agent.agent_name,
        recipient=citation_agent.agent_name,
        task="attach_citations",
        trace_id=trace_id,
        payload={"paper": merged_writing_result.model_dump(mode="python")},
        response_model=CitationAgentOutput,
        require_references=True,
        validation_events=validation_events,
    )

    formatting_result, formatting_dispatch = await _dispatch_validated_stage(
        a2a_manager=a2a_manager,
        sender=citation_agent.agent_name,
        recipient=formatting_agent.agent_name,
        task="format_ieee_paper",
        trace_id=trace_id,
        payload={
            "paper": citation_result.model_dump(mode="python"),
            "figures": formatting_figures,
            "tables": formatting_tables,
        },
        response_model=FormattingAgentOutput,
        require_references=True,
        validation_events=validation_events,
    )

    if formatting_result.error is not None:
        _raise_agent_runtime_error(
            agent_name=formatting_agent.agent_name,
            error_payload=formatting_result.error,
            default_message="Formatting failed.",
        )

    humanizer_started = perf_counter()
    humanizer_result = _execute_humanizer_loop(
        humanizer_agent=humanizer_agent,
        paper=formatting_result.paper,
        trace_id=trace_id,
        pipeline_context=pipeline_context,
    )
    humanizer_duration_ms = (perf_counter() - humanizer_started) * 1000
    humanizer_issues = validate_research_paper(
        humanizer_result.paper,
        require_references=True,
    )
    if not humanizer_result.formatted_text.strip():
        humanizer_issues.append("formatted_text is empty")
    if not humanizer_result.latex_ready.strip():
        humanizer_issues.append("latex_ready is empty")
    if humanizer_issues:
        raise PaperValidationError(humanizer_agent.agent_name, humanizer_issues)
    validation_events.append(
        f"{humanizer_agent.agent_name}: completed with action {humanizer_result.graph_action or 'accept'}"
    )

    originality_result, originality_dispatch = await _dispatch_validated_stage(
        a2a_manager=a2a_manager,
        sender=humanizer_agent.agent_name,
        recipient=originality_agent.agent_name,
        task="review_originality_and_compliance",
        trace_id=trace_id,
        payload={
            "paper": humanizer_result.model_dump(),
            "citation_draft": citation_result.citation_draft,
        },
        response_model=OriginalityAgentOutput,
        require_references=True,
        validation_events=validation_events,
    )

    if originality_result.error is not None:
        _raise_agent_runtime_error(
            agent_name=originality_agent.agent_name,
            error_payload=originality_result.error,
            default_message="Originality review failed.",
        )

    total_duration_ms = (perf_counter() - start_time) * 1000
    originality_report = originality_result.originality_report or {}
    section_reports = originality_report.get("sections") or {}
    flagged_span_count = sum(len((section or {}).get("spans") or []) for section in section_reports.values())
    metadata = GenerationMetadata(
        model=resolved_settings.vertex_model,
        generation_time_ms=total_duration_ms,
        source_text_length=len(text),
        trace_id=trace_id,
        agent_timings=[
            AgentTiming(agent=structuring_agent.agent_name, duration_ms=structuring_dispatch.duration_ms),
            AgentTiming(agent=writing_agent.agent_name, duration_ms=writing_dispatch.duration_ms),
            AgentTiming(agent=figure_table_agent.agent_name, duration_ms=figure_table_duration_ms),
            AgentTiming(agent=citation_agent.agent_name, duration_ms=citation_dispatch.duration_ms),
            AgentTiming(agent=formatting_agent.agent_name, duration_ms=formatting_dispatch.duration_ms),
            AgentTiming(agent=humanizer_agent.agent_name, duration_ms=humanizer_duration_ms),
            AgentTiming(agent=originality_agent.agent_name, duration_ms=originality_dispatch.duration_ms),
        ],
        mcp_tools_used=registry.get("citation_agent").enabled_tools,
        validation_events=validation_events,
        structuring_global_confidence=structuring_result.global_confidence,
        structuring_section_confidences=structuring_result.section_confidences,
        structuring_evidence_summary=structuring_result.evidence_summary,
        writing_global_confidence=writing_result.global_confidence,
        writing_section_confidences=writing_result.section_confidences,
        writing_annotation_summary=writing_result.annotation_summary,
        citation_match_count=citation_result.matched_claim_count,
        citation_bibliography_count=citation_result.bibliography_count,
        citation_provider_summary=citation_result.provider_summary,
        figure_table_figure_count=int(pipeline_context.get("generated_figure_count") or 0),
        figure_table_table_count=int(pipeline_context.get("generated_table_count") or 0),
        formatting_compile_success=formatting_result.compile_success,
        formatting_retry_recommended=formatting_result.retry_recommended,
        formatting_diagnostic_summary=formatting_result.diagnostic_summary,
        humanizer_ai_pattern_score_before=humanizer_result.ai_pattern_score_before,
        humanizer_ai_pattern_score_after=humanizer_result.ai_pattern_score_after,
        humanizer_perplexity_before=humanizer_result.perplexity_before,
        humanizer_perplexity_after=humanizer_result.perplexity_after,
        humanizer_iterations=humanizer_result.iteration_count,
        humanizer_graph_action=humanizer_result.graph_action,
        originality_provider_used=originality_result.provider_used,
        originality_global_score=originality_result.global_originality_score,
        originality_global_ai_score=originality_result.global_ai_score,
        originality_section_status_counts=originality_result.section_status_counts,
        originality_decision=originality_result.decision_graph_action,
        originality_flagged_span_count=flagged_span_count,
    )

    if originality_result.approved_snapshot is None:
        raise OriginalityReviewBlockedError(
            message="The manuscript requires originality or compliance review before approval.",
            details={
                "trace_id": trace_id,
                "graph_action": originality_result.decision_graph_action or "needs_manual_review",
                "originality_report": originality_report,
            },
        )

    generated_paper = originality_result.approved_snapshot

    logger.info("Pipeline trace %s completed in %.2f ms", trace_id, total_duration_ms)
    return PipelineResult(
        generated_paper=generated_paper,
        metadata=metadata,
        generated_figures=pipeline_context.get("generated_figures"),
        generated_tables=pipeline_context.get("generated_tables"),
        figure_table_status=pipeline_context.get("figure_table_status"),
        figure_table_error=pipeline_context.get("figure_table_error"),
    )
