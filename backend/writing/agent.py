"""Writing runtime plus the ADK-facing entrypoint.

The runtime is intentionally independent from ADK so the current in-process
pipeline, future LangGraph nodes, and tests can all use the same writing logic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from google.genai import types
from pydantic import Field, ValidationError

from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from models.generation import ResearchPaperSchema
from structuring.schemas import StructuredPaperDraft
from writing.config import WritingConfig
from writing.schemas import WritingAgentError, WritingAgentResult, build_paper_snapshot
from writing.section_writer import write_paper

logger = logging.getLogger("papereasy.backend.writing.agent")

try:  # pragma: no cover - environment dependent import
    from google.adk.agents import BaseAgent as ADKBaseAgent
    from google.adk.events import Event

    ADK_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - environment dependent
    ADKBaseAgent = None
    Event = None
    ADK_IMPORT_ERROR = exc


@dataclass(frozen=True)
class WritingRuntime:
    settings: Settings
    config: WritingConfig
    vertex_client: VertexGeminiClient


async def run_writing_pipeline(
    *,
    structured_draft: object,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    author_metadata: object | None = None,
    writing_style_preferences: object | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: WritingConfig | None = None,
    vertex_client: VertexGeminiClient | None = None,
    fallback_keywords: list[str] | None = None,
    fallback_references: list[str] | None = None,
    logger_: logging.Logger | None = None,
) -> WritingAgentResult:
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or WritingConfig.from_settings(resolved_settings)
    resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())

    active_logger.info("Writing trace %s started.", resolved_trace_id)

    if structured_draft in (None, "", {}):
        return _build_error_result(
            code="missing_structured_draft",
            message="The writing agent requires a structured_draft input.",
            trace_id=resolved_trace_id,
            details={},
        )

    try:
        parsed_draft = StructuredPaperDraft.model_validate(structured_draft)
    except ValidationError as exc:
        return _build_error_result(
            code="invalid_structured_draft",
            message="The structured_draft payload is malformed and could not be parsed.",
            trace_id=resolved_trace_id,
            details={"validation_errors": exc.errors()},
        )

    section_confidence_log = {
        section_name: round(section.confidence, 4)
        for section_name, section in parsed_draft.sections.items()
    }
    active_logger.info(
        "Writing trace %s section confidences=%s",
        resolved_trace_id,
        section_confidence_log,
    )

    written_draft, section_confidences, annotation_summary, title_backend = await write_paper(
        structured_draft=parsed_draft,
        config=resolved_config,
        vertex_client=resolved_client,
        paper_topic=(paper_topic or "").strip(),
        paper_domain=(paper_domain or "").strip(),
        author_metadata=str(author_metadata or "").strip(),
        writing_style_preferences=str(writing_style_preferences or "").strip(),
        trace_id=resolved_trace_id,
        fallback_keywords=fallback_keywords,
        fallback_references=fallback_references,
        logger_=active_logger,
    )

    paper_snapshot = build_paper_snapshot(
        title=written_draft.title,
        abstract=written_draft.abstract.text,
        keywords=list(written_draft.metadata.get("keywords", fallback_keywords or [])),
        sections=written_draft.sections,
        references=fallback_references or list(written_draft.metadata.get("fallback_references", [])),
    )
    active_logger.info(
        "Writing trace %s completed with global confidence %.4f using title backend %s.",
        resolved_trace_id,
        written_draft.global_confidence,
        title_backend,
    )
    return WritingAgentResult(
        written_draft=written_draft,
        paper_snapshot=paper_snapshot,
        trace_id=resolved_trace_id,
        metadata={
            "section_confidences": section_confidences,
            "annotation_summary": annotation_summary,
            "title_backend": title_backend,
        },
    )


if ADKBaseAgent is not None:

    class WritingAgent(ADKBaseAgent):
        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: WritingConfig = Field(default_factory=WritingConfig.from_settings, exclude=True)
        vertex_client: VertexGeminiClient | None = Field(default=None, exclude=True)

        def __init__(
            self,
            *,
            settings: Settings | None = None,
            config: WritingConfig | None = None,
            vertex_client: VertexGeminiClient | None = None,
        ):
            resolved_settings = settings or get_settings()
            resolved_config = config or WritingConfig.from_settings(resolved_settings)
            resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
            super().__init__(
                name="writing_agent",
                description="Rewrites the structured IEEE skeleton into polished academic prose using section-specific persona prompting and evidence-aware generation.",
                settings=resolved_settings,
                config=resolved_config,
                vertex_client=resolved_client,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_writing_pipeline(
                structured_draft=state.get("structured_draft"),
                paper_topic=_coerce_optional_text(state.get("paper_topic")),
                paper_domain=_coerce_optional_text(state.get("paper_domain")),
                author_metadata=state.get("author_metadata"),
                writing_style_preferences=state.get("writing_style_preferences"),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
                vertex_client=self.vertex_client,
            )

            if result.written_draft is not None:
                state["written_draft"] = result.written_draft.model_dump(mode="python")
            if result.paper_snapshot is not None:
                state["written_paper_snapshot"] = result.paper_snapshot.model_dump(mode="python")
            if result.error is not None:
                state["written_draft_error"] = result.error.model_dump(mode="python")

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

    class WritingAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


def build_runtime(
    settings: Settings | None = None,
    config: WritingConfig | None = None,
    vertex_client: VertexGeminiClient | None = None,
) -> WritingRuntime:
    resolved_settings = settings or get_settings()
    resolved_config = config or WritingConfig.from_settings(resolved_settings)
    resolved_client = vertex_client or VertexGeminiClient(resolved_settings)
    return WritingRuntime(
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
) -> WritingAgentResult:
    return WritingAgentResult(
        error=WritingAgentError(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details,
        ),
        trace_id=trace_id,
        metadata={"status": "error"},
    )


def _coerce_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


runtime = build_runtime()
if ADKBaseAgent is not None:  # pragma: no branch
    agent = WritingAgent(
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
            logger.warning("Unable to build A2A app for the writing agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the writing agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
