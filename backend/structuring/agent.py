"""Evidence-driven structuring runtime plus the ADK-facing agent wrapper.

The runtime is intentionally separate from the ADK class so the current pipeline,
future LangGraph nodes, and unit tests can all reuse the same logic.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from statistics import mean
from time import perf_counter
from typing import Any
from uuid import uuid4

from google.genai import types
from pydantic import Field

from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from models.generation import IEEESectionMap, ResearchPaperSchema
from structuring.chunking import chunk_source_text, normalize_source_text
from structuring.config import StructuringConfig
from structuring.retrieval import EmbeddingProvider, retrieve_section_candidates
from structuring.schemas import (
    REQUIRED_STRUCTURING_SECTIONS,
    SectionSkeleton,
    StructuredPaperDraft,
    StructuringAgentError,
    StructuringAgentResult,
)
from structuring.summarizer import (
    SectionReducer,
    VertexSectionReducer,
    build_section_skeleton,
    build_title_candidates,
    extract_keywords,
    map_chunks_to_evidence_notes,
)

logger = logging.getLogger("papereasy.backend.structuring.agent")

try:  # pragma: no cover - environment dependent import
    from google.adk.agents import BaseAgent as ADKBaseAgent
    from google.adk.events import Event

    ADK_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - environment dependent
    ADKBaseAgent = None
    Event = None
    ADK_IMPORT_ERROR = exc


@dataclass(frozen=True)
class StructuringRuntime:
    settings: Settings
    config: StructuringConfig
    vertex_client: VertexGeminiClient


async def run_structuring_pipeline(
    *,
    source_text: str,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    author_metadata: Any | None = None,
    max_input_chars: int | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: StructuringConfig | None = None,
    vertex_client: VertexGeminiClient | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reducer: SectionReducer | None = None,
    logger_: logging.Logger | None = None,
) -> StructuringAgentResult:
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or StructuringConfig.from_settings(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())
    resolved_vertex_client = vertex_client or VertexGeminiClient(resolved_settings)
    input_limit = _resolve_max_input_chars(
        requested=max_input_chars,
        settings=resolved_settings,
    )
    normalized_source = normalize_source_text(source_text, input_limit)
    context = {
        "paper_topic": (paper_topic or "").strip(),
        "paper_domain": (paper_domain or "").strip(),
        "author_metadata": str(author_metadata or "").strip(),
    }

    active_logger.info(
        "Structuring trace %s started for %s normalized source characters.",
        resolved_trace_id,
        len(normalized_source),
    )

    if not normalized_source:
        return _build_error_result(
            code="empty_source_text",
            message="No source text was provided to the structuring agent.",
            trace_id=resolved_trace_id,
            source_text=normalized_source,
            context=context,
            config=resolved_config,
        )

    if len(normalized_source) < resolved_config.minimum_source_chars:
        return _build_error_result(
            code="source_text_too_short",
            message="The source text is too short to build a reliable IEEE paper skeleton.",
            trace_id=resolved_trace_id,
            source_text=normalized_source,
            context=context,
            config=resolved_config,
        )

    timings_ms: dict[str, float] = {}

    chunk_start = perf_counter()
    chunks = chunk_source_text(normalized_source, resolved_config)
    timings_ms["chunking"] = round((perf_counter() - chunk_start) * 1000, 2)
    active_logger.info("Structuring trace %s produced %s chunks.", resolved_trace_id, len(chunks))
    if not chunks:
        return _build_error_result(
            code="chunking_failed",
            message="The structuring agent could not create any chunks from the source text.",
            trace_id=resolved_trace_id,
            source_text=normalized_source,
            context=context,
            config=resolved_config,
        )

    retrieval_start = perf_counter()
    retrieval_results, retrieval_backend = retrieve_section_candidates(
        chunks=chunks,
        config=resolved_config,
        settings=resolved_settings,
        paper_topic=context["paper_topic"] or None,
        paper_domain=context["paper_domain"] or None,
        embedding_provider=embedding_provider,
        logger_=active_logger,
    )
    timings_ms["retrieval"] = round((perf_counter() - retrieval_start) * 1000, 2)
    retrieval_counts = {
        section_name: len(result.candidates)
        for section_name, result in retrieval_results.items()
    }
    active_logger.info(
        "Structuring trace %s retrieval backend=%s counts=%s",
        resolved_trace_id,
        retrieval_backend,
        retrieval_counts,
    )

    active_reducer = reducer
    if active_reducer is None:
        active_reducer = VertexSectionReducer(
            client=resolved_vertex_client,
            model_name=resolved_config.reducer_model,
        )

    section_start = perf_counter()
    section_semaphore = asyncio.Semaphore(resolved_config.max_parallel_section_reductions)
    section_tasks = [
        _build_section_result(
            section_name=section_name,
            retrieval_results=retrieval_results,
            reducer=active_reducer,
            context=context,
            config=resolved_config,
            semaphore=section_semaphore,
        )
        for section_name in REQUIRED_STRUCTURING_SECTIONS
    ]
    title_notes = map_chunks_to_evidence_notes(
        section_name="title",
        ranked_chunks=retrieval_results.get("title").candidates if retrieval_results.get("title") else [],
        config=resolved_config,
    )
    title_task = asyncio.create_task(
        build_title_candidates(
            source_text=normalized_source,
            title_notes=title_notes,
            reducer=active_reducer,
            context=context,
            config=resolved_config,
        )
    )
    section_results = await asyncio.gather(*section_tasks)
    section_summaries: dict[str, SectionSkeleton] = {
        section_name: section_skeleton
        for section_name, _notes, section_skeleton in section_results
    }
    evidence_notes: dict[str, list] = {
        section_name: notes
        for section_name, notes, _section_skeleton in section_results
    }
    timings_ms["summarization"] = round((perf_counter() - section_start) * 1000, 2)

    titles = await title_task

    global_confidence = round(
        mean(section.confidence for section in section_summaries.values()),
        4,
    )
    structured_draft = StructuredPaperDraft(
        title_candidates=titles,
        sections=section_summaries,
        evidence_notes=evidence_notes,
        global_confidence=global_confidence,
        metadata={
            "trace_id": resolved_trace_id,
            "chunk_count": len(chunks),
            "retrieval_backend": retrieval_backend,
            "retrieval_counts": retrieval_counts,
            "timings_ms": timings_ms,
            "paper_topic": context["paper_topic"],
            "paper_domain": context["paper_domain"],
            "author_metadata": context["author_metadata"],
        },
    )
    paper_snapshot = _build_paper_snapshot(
        structured_draft=structured_draft,
        source_text=normalized_source,
        context=context,
    )
    active_logger.info(
        "Structuring trace %s completed with global confidence %.4f.",
        resolved_trace_id,
        structured_draft.global_confidence,
    )
    return StructuringAgentResult(
        structured_draft=structured_draft,
        paper_snapshot=paper_snapshot,
        trace_id=resolved_trace_id,
        metadata={
            "timings_ms": timings_ms,
            "retrieval_backend": retrieval_backend,
        },
    )


if ADKBaseAgent is not None:

    class StructuringAgent(ADKBaseAgent):
        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: StructuringConfig = Field(default_factory=StructuringConfig.from_settings, exclude=True)
        vertex_client: VertexGeminiClient | None = Field(default=None, exclude=True)

        def __init__(
            self,
            *,
            settings: Settings | None = None,
            config: StructuringConfig | None = None,
            vertex_client: VertexGeminiClient | None = None,
        ):
            resolved_settings = settings or get_settings()
            resolved_config = config or StructuringConfig.from_settings(resolved_settings)
            resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
            super().__init__(
                name="structuring_agent",
                description="Converts raw source text into a structured IEEE paper skeleton with evidence map.",
                settings=resolved_settings,
                config=resolved_config,
                vertex_client=resolved_client,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_structuring_pipeline(
                source_text=str(state.get("source_text", "")),
                paper_topic=_coerce_optional_text(state.get("paper_topic")),
                paper_domain=_coerce_optional_text(state.get("paper_domain")),
                author_metadata=state.get("author_metadata"),
                max_input_chars=_coerce_optional_int(state.get("max_input_chars")),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
                vertex_client=self.vertex_client,
            )

            if result.structured_draft is not None:
                state["structured_draft"] = result.structured_draft.model_dump(mode="python")
            if result.paper_snapshot is not None:
                state["structured_paper_snapshot"] = result.paper_snapshot.model_dump(mode="python")
            if result.error is not None:
                state["structured_draft_error"] = result.error.model_dump(mode="python")

            yield Event(
                invocationId=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                turnComplete=True,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=result.model_dump_json(indent=2),
                        )
                    ],
                ),
            )

else:

    class StructuringAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


def build_runtime(
    settings: Settings | None = None,
    config: StructuringConfig | None = None,
    vertex_client: VertexGeminiClient | None = None,
) -> StructuringRuntime:
    resolved_settings = settings or get_settings()
    resolved_config = config or StructuringConfig.from_settings(resolved_settings)
    resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
    return StructuringRuntime(
        settings=resolved_settings,
        config=resolved_config,
        vertex_client=resolved_client,
    )


def _resolve_max_input_chars(*, requested: object | None, settings: Settings) -> int:
    if requested is None or requested == "":
        return settings.ai_source_text_max_chars
    try:
        requested_int = int(requested)
    except (TypeError, ValueError):
        return settings.ai_source_text_max_chars
    if requested_int <= 0:
        return settings.ai_source_text_max_chars
    return min(requested_int, settings.ai_source_text_max_chars)


async def _build_section_result(
    *,
    section_name: str,
    retrieval_results,
    reducer: SectionReducer | None,
    context: dict[str, str],
    config: StructuringConfig,
    semaphore: asyncio.Semaphore,
) -> tuple[str, list, SectionSkeleton]:
    ranked_chunks = retrieval_results.get(section_name)
    candidates = ranked_chunks.candidates if ranked_chunks is not None else []
    notes = map_chunks_to_evidence_notes(
        section_name=section_name,
        ranked_chunks=candidates,
        config=config,
    )
    async with semaphore:
        section_skeleton = await build_section_skeleton(
            section_name=section_name,
            notes=notes,
            ranked_chunks=candidates,
            reducer=reducer,
            context=context,
            config=config,
        )
    return section_name, notes, section_skeleton


def _build_paper_snapshot(
    *,
    structured_draft: StructuredPaperDraft,
    source_text: str,
    context: dict[str, str],
) -> ResearchPaperSchema:
    title = structured_draft.title_candidates[0] if structured_draft.title_candidates else "Structured Research Paper Draft"
    keywords = extract_keywords(
        source_text=source_text,
        section_summaries=structured_draft.sections,
        context=context,
    )
    return ResearchPaperSchema(
        title=title,
        abstract=structured_draft.sections["abstract"].draft or "Abstract evidence requires author review.",
        keywords=keywords,
        sections=IEEESectionMap(
            introduction=structured_draft.sections["introduction"].draft or "Introduction evidence requires author review.",
            related_work=structured_draft.sections["related_work"].draft or "Related work evidence requires author review.",
            methodology=structured_draft.sections["methodology"].draft or "Methodology evidence requires author review.",
            results=structured_draft.sections["results"].draft or "Results evidence requires author review.",
            discussion=structured_draft.sections["discussion"].draft or "Discussion evidence requires author review.",
            limitations=structured_draft.sections["limitations"].draft or "Limitations evidence requires author review.",
            conclusion=structured_draft.sections["conclusion"].draft or "Conclusion evidence requires author review.",
        ),
        references=[],
    )


def _build_error_result(
    *,
    code: str,
    message: str,
    trace_id: str,
    source_text: str,
    context: dict[str, str],
    config: StructuringConfig,
) -> StructuringAgentResult:
    placeholder_sections = {
        section_name: SectionSkeleton(
            section_name=section_name,
            draft=f"Insufficient evidence available for {section_name.replace('_', ' ')}.",
            confidence=0.05,
            key_points=[],
            source_spans=[],
            missing_evidence=[message],
            direct_evidence=[],
            inferred_synthesis=[],
        )
        for section_name in REQUIRED_STRUCTURING_SECTIONS
    }
    structured_draft = StructuredPaperDraft(
        title_candidates=[context.get("paper_topic") or "Structured Research Paper Draft"],
        sections=placeholder_sections,
        evidence_notes={section_name: [] for section_name in REQUIRED_STRUCTURING_SECTIONS},
        global_confidence=0.05,
        metadata={
            "trace_id": trace_id,
            "chunk_count": 0,
            "retrieval_backend": "none",
            "paper_topic": context.get("paper_topic", ""),
            "paper_domain": context.get("paper_domain", ""),
        },
    )
    return StructuringAgentResult(
        structured_draft=structured_draft,
        paper_snapshot=_build_paper_snapshot(
            structured_draft=structured_draft,
            source_text=source_text,
            context=context,
        ),
        error=StructuringAgentError(
            code=code,
            message=message,
            trace_id=trace_id,
            recoverable=True,
            details={
                "source_length": len(source_text),
                "minimum_source_chars": config.minimum_source_chars,
            },
        ),
        trace_id=trace_id,
        metadata={"status": "error"},
    )


def _coerce_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


runtime = build_runtime()
if ADKBaseAgent is not None:  # pragma: no branch
    agent = StructuringAgent(
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
            logger.warning("Unable to build A2A app for the structuring agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the structuring agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
