"""Citation runtime plus the ADK-facing entrypoint.

The runtime is independent from ADK so the current in-process pipeline,
future LangGraph nodes, and tests all use the same claim-level retrieval stack.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationError

from citation.config import CitationConfig
from citation.retrieval import build_citation_draft
from citation.schemas import CitationAgentError, CitationAgentResult
from core.config import Settings, get_settings
from structuring.schemas import StructuredPaperDraft
from writing.schemas import WrittenPaperDraft, build_paper_snapshot

logger = logging.getLogger("papereasy.backend.citation.agent")

MANUAL_REVIEW_REFERENCE = "[1] Reference curation pending manual review."

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
class CitationRuntime:
    settings: Settings
    config: CitationConfig


async def run_citation_pipeline(
    *,
    written_draft: object,
    structured_draft: object | None = None,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    author_metadata: object | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: CitationConfig | None = None,
    fallback_keywords: list[str] | None = None,
    semantic_scholar_client=None,
    openalex_client=None,
    pubmed_client=None,
    doi_client=None,
    logger_: logging.Logger | None = None,
) -> CitationAgentResult:
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or CitationConfig.from_settings(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())

    if written_draft in (None, "", {}):
        return _build_error_result(
            code="missing_written_draft",
            message="The citation agent requires a written_draft input.",
            trace_id=resolved_trace_id,
            details={},
        )

    try:
        parsed_written_draft = WrittenPaperDraft.model_validate(written_draft)
    except ValidationError as exc:
        return _build_error_result(
            code="invalid_written_draft",
            message="The written_draft payload is malformed and could not be parsed.",
            trace_id=resolved_trace_id,
            details={"validation_errors": exc.errors()},
        )

    parsed_structured_draft: StructuredPaperDraft | None = None
    if structured_draft not in (None, "", {}):
        try:
            parsed_structured_draft = StructuredPaperDraft.model_validate(structured_draft)
        except ValidationError as exc:
            active_logger.warning("Citation trace %s received invalid structured_draft: %s", resolved_trace_id, exc)

    citation_draft = await build_citation_draft(
        written_draft=parsed_written_draft,
        structured_draft=parsed_structured_draft,
        config=resolved_config,
        settings=resolved_settings,
        paper_topic=(paper_topic or "").strip() or None,
        paper_domain=(paper_domain or "").strip() or None,
        trace_id=resolved_trace_id,
        semantic_scholar_client=semantic_scholar_client,
        openalex_client=openalex_client,
        pubmed_client=pubmed_client,
        doi_client=doi_client,
        logger_=active_logger,
    )
    if not citation_draft.bibliography:
        paper_snapshot = build_paper_snapshot(
            title=parsed_written_draft.title,
            abstract=parsed_written_draft.abstract.text,
            keywords=list(parsed_written_draft.metadata.get("keywords", fallback_keywords or [])),
            sections=parsed_written_draft.sections,
            references=[MANUAL_REVIEW_REFERENCE],
        )
        return CitationAgentResult(
            citation_draft=citation_draft,
            paper_snapshot=paper_snapshot,
            error=CitationAgentError(
                code="no_citations_found",
                message="The citation agent could not validate any external scholarly references for the current draft.",
                trace_id=resolved_trace_id,
                details={
                    "matched_claim_count": citation_draft.matched_claim_count,
                    "provider_summary": citation_draft.provider_summary,
                    "manual_review_required": True,
                },
            ),
            trace_id=resolved_trace_id,
            metadata={
                "provider_summary": citation_draft.provider_summary,
                "matched_claim_count": citation_draft.matched_claim_count,
                "bibliography_count": citation_draft.bibliography_count,
                "manual_review_required": True,
            },
        )

    paper_snapshot = build_paper_snapshot(
        title=parsed_written_draft.title,
        abstract=parsed_written_draft.abstract.text,
        keywords=list(parsed_written_draft.metadata.get("keywords", fallback_keywords or [])),
        sections=parsed_written_draft.sections,
        references=[entry.ieee_reference for entry in citation_draft.bibliography],
    )
    return CitationAgentResult(
        citation_draft=citation_draft,
        paper_snapshot=paper_snapshot,
        trace_id=resolved_trace_id,
        metadata={
            "provider_summary": citation_draft.provider_summary,
            "matched_claim_count": citation_draft.matched_claim_count,
            "bibliography_count": citation_draft.bibliography_count,
        },
    )


if ADKBaseAgent is not None:

    class CitationAgent(ADKBaseAgent):
        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: CitationConfig = Field(default_factory=CitationConfig.from_settings, exclude=True)

        def __init__(self, *, settings: Settings | None = None, config: CitationConfig | None = None):
            resolved_settings = settings or get_settings()
            resolved_config = config or CitationConfig.from_settings(resolved_settings)
            super().__init__(
                name="citation_agent",
                description="Matches scholarly citations to evidence-backed claims using real academic APIs and DOI validation.",
                settings=resolved_settings,
                config=resolved_config,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_citation_pipeline(
                written_draft=state.get("written_draft"),
                structured_draft=state.get("structured_draft"),
                paper_topic=_coerce_optional_text(state.get("paper_topic")),
                paper_domain=_coerce_optional_text(state.get("paper_domain")),
                author_metadata=state.get("author_metadata"),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
            )

            if result.citation_draft is not None:
                state["citation_draft"] = result.citation_draft.model_dump(mode="python")
            if result.paper_snapshot is not None:
                state["cited_paper_snapshot"] = result.paper_snapshot.model_dump(mode="python")
            if result.error is not None:
                state["citation_error"] = result.error.model_dump(mode="python")

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

    class CitationAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


def build_runtime(settings: Settings | None = None, config: CitationConfig | None = None) -> CitationRuntime:
    resolved_settings = settings or get_settings()
    resolved_config = config or CitationConfig.from_settings(resolved_settings)
    return CitationRuntime(settings=resolved_settings, config=resolved_config)


def _build_error_result(*, code: str, message: str, trace_id: str, details: dict[str, Any]) -> CitationAgentResult:
    return CitationAgentResult(
        error=CitationAgentError(
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
    agent = CitationAgent(settings=runtime.settings, config=runtime.config)

    try:  # pragma: no cover - optional A2A runtime wiring
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("ADK A2A bridge is unavailable: %s", exc)
        to_a2a = None

    if to_a2a is not None:  # pragma: no cover - environment dependent
        try:
            app = to_a2a(agent, public_url=os.environ.get("PUBLIC_URL"))
        except Exception as exc:
            logger.warning("Unable to build A2A app for the citation agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the citation agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
