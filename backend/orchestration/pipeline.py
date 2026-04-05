from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from agents.citation_agent import CitationAgent
from agents.formatting_agent import FormattingAgent
from agents.structuring_agent import StructuringAgent
from agents.writing_agent import WritingAgent
from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from mcp.mcp_server import build_default_mcp_server
from models.generation import (
    AgentTiming,
    CitationAgentOutput,
    FormattingAgentOutput,
    GenerationMetadata,
    PipelineResult,
    StructuringAgentOutput,
    WritingAgentOutput,
)
from orchestration.a2a_manager import A2AManager


async def run_pipeline(text: str, settings: Settings | None = None) -> PipelineResult:
    resolved_settings = settings or get_settings()
    trace_id = str(uuid4())
    start_time = perf_counter()

    vertex_client = VertexGeminiClient(resolved_settings)
    mcp_server = build_default_mcp_server()
    a2a_manager = A2AManager(resolved_settings)

    structuring_agent = StructuringAgent(vertex_client, resolved_settings)
    writing_agent = WritingAgent(vertex_client)
    citation_agent = CitationAgent(mcp_server, resolved_settings)
    formatting_agent = FormattingAgent()

    for agent in [structuring_agent, writing_agent, citation_agent, formatting_agent]:
        a2a_manager.register(agent)

    structuring_result = await a2a_manager.dispatch(
        sender="pipeline",
        recipient=structuring_agent.agent_name,
        task="structure_document",
        trace_id=trace_id,
        payload={"raw_text": text},
    )
    structured_sections = StructuringAgentOutput.model_validate(structuring_result.payload)

    writing_result = await a2a_manager.dispatch(
        sender=structuring_agent.agent_name,
        recipient=writing_agent.agent_name,
        task="improve_sections",
        trace_id=trace_id,
        payload={"sections": structured_sections.model_dump()},
    )
    polished_sections = WritingAgentOutput.model_validate(writing_result.payload)

    citation_result = await a2a_manager.dispatch(
        sender=writing_agent.agent_name,
        recipient=citation_agent.agent_name,
        task="attach_citations",
        trace_id=trace_id,
        payload={"sections": polished_sections.model_dump()},
    )
    cited_sections = CitationAgentOutput.model_validate(citation_result.payload)

    formatting_result = await a2a_manager.dispatch(
        sender=citation_agent.agent_name,
        recipient=formatting_agent.agent_name,
        task="format_ieee_paper",
        trace_id=trace_id,
        payload=cited_sections.model_dump(),
    )
    final_paper = FormattingAgentOutput.model_validate(formatting_result.payload)

    total_duration_ms = (perf_counter() - start_time) * 1000
    metadata = GenerationMetadata(
        model=resolved_settings.vertex_model,
        generation_time_ms=total_duration_ms,
        source_text_length=len(text),
        trace_id=trace_id,
        agent_timings=[
            AgentTiming(agent=structuring_agent.agent_name, duration_ms=structuring_result.duration_ms),
            AgentTiming(agent=writing_agent.agent_name, duration_ms=writing_result.duration_ms),
            AgentTiming(agent=citation_agent.agent_name, duration_ms=citation_result.duration_ms),
            AgentTiming(agent=formatting_agent.agent_name, duration_ms=formatting_result.duration_ms),
        ],
        mcp_tools_used=["search_tool", "citation_tool"],
    )
    return PipelineResult(generated_paper=final_paper, metadata=metadata)
