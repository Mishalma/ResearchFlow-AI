from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from agents.citation_agent import CitationAgent
from agents.ieee_formatting_agent import IEEEFormattingAgent
from agents.registry import get_agent_registry
from agents.structuring_agent import StructuringAgent
from agents.writing_agent import WritingAgent
from app.services.paper_service import validate_research_paper
from core.config import Settings, get_settings
from core.exceptions import InvalidAgentResponseError, PaperValidationError
from core.vertex_client import VertexGeminiClient
from mcp.mcp_server import build_default_mcp_server
from models.generation import (
    AgentTiming,
    CitationAgentOutput,
    FormattingAgentOutput,
    GeneratedPaper,
    GenerationMetadata,
    PipelineResult,
    ResearchPaperSchema,
    StructuringAgentOutput,
    WritingAgentOutput,
)
from orchestration.a2a_manager import A2AManager, InProcessTransport

logger = logging.getLogger("papereasy.backend.pipeline")


def _paper_summary(paper: ResearchPaperSchema) -> str:
    completed_sections = [
        key
        for key in (
            "introduction",
            "related_work",
            "methodology",
            "results",
            "discussion",
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

        paper = structured_result if isinstance(structured_result, ResearchPaperSchema) else structured_result.paper
        issues = validate_research_paper(paper, require_references=require_references)

        if isinstance(structured_result, FormattingAgentOutput):
            if not structured_result.formatted_text.strip():
                issues.append("formatted_text is empty")
            if not structured_result.latex_ready.strip():
                issues.append("latex_ready is empty")

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


async def run_pipeline(text: str, settings: Settings | None = None) -> PipelineResult:
    resolved_settings = settings or get_settings()
    trace_id = str(uuid4())
    start_time = perf_counter()
    validation_events: list[str] = []

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

    for agent in [structuring_agent, writing_agent, citation_agent, formatting_agent]:
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

    total_duration_ms = (perf_counter() - start_time) * 1000
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
        ],
        mcp_tools_used=registry.get("citation_agent").enabled_tools,
        validation_events=validation_events,
    )

    generated_paper = GeneratedPaper(
        paper=formatting_result.paper,
        formatted_text=formatting_result.formatted_text,
        latex_ready=formatting_result.latex_ready,
    )

    logger.info("Pipeline trace %s completed in %.2f ms", trace_id, total_duration_ms)
    return PipelineResult(generated_paper=generated_paper, metadata=metadata)
