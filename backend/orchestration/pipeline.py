from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from agents.citation_agent import CitationAgent
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


async def run_pipeline(text: str, settings: Settings | None = None) -> PipelineResult:
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
    citation_agent = CitationAgent(
        mcp_server,
        registry.get("citation_agent"),
        resolved_settings,
    )
    formatting_agent = IEEEFormattingAgent(registry.get("ieee_formatting_agent"))
    humanizer_agent = HumanizerAgent(vertex_client, registry.get("humanizer_agent"))
    originality_agent = OriginalityAgent(registry.get("originality_agent"))

    for agent in [structuring_agent, writing_agent, citation_agent, formatting_agent, humanizer_agent, originality_agent]:
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

    citation_result, citation_dispatch = await _dispatch_validated_stage(
        a2a_manager=a2a_manager,
        sender=writing_agent.agent_name,
        recipient=citation_agent.agent_name,
        task="attach_citations",
        trace_id=trace_id,
        payload={"paper": writing_result.model_dump()},
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
        payload={"paper": citation_result.model_dump()},
        response_model=FormattingAgentOutput,
        require_references=True,
        validation_events=validation_events,
    )

    if formatting_result.error is not None:
        raise AgentExecutionError(
            formatting_agent.agent_name,
            message=str(formatting_result.error.get("message") or "Formatting failed."),
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
        raise AgentExecutionError(
            originality_agent.agent_name,
            message=str(originality_result.error.get("message") or "Originality review failed."),
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
    return PipelineResult(generated_paper=generated_paper, metadata=metadata)
