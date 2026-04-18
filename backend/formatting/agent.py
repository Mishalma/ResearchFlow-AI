"""Formatting runtime plus the guarded ADK-facing entrypoint.

The runtime is independent from ADK so the current in-process pipeline,
future LangGraph nodes, and tests all use the same compile-and-validate stack.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationError

from core.config import Settings, get_settings
from formatting.compiler import compile_latex_document
from formatting.config import FormattingConfig
from formatting.preview import generate_html_preview
from formatting.schemas import FormattingAgentError, FormattingAgentResult
from formatting.template_engine import render_latex_document
from formatting.utils import (
    build_author_blocks,
    build_document_context,
    build_legacy_paper_snapshot,
    create_work_dir,
    maybe_cleanup_work_dir,
    summarize_diagnostics,
    validate_input_content,
)
from models.generation import ResearchPaperSchema

logger = logging.getLogger("papereasy.backend.formatting.agent")

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
class FormattingRuntime:
    settings: Settings
    config: FormattingConfig


async def run_formatting_pipeline(
    *,
    paper: object,
    author_metadata: object | None = None,
    paper_metadata: object | None = None,  # reserved for future template expansion
    figures: dict[str, list[dict[str, object]]] | None = None,
    tables: dict[str, list[dict[str, object]]] | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: FormattingConfig | None = None,
    logger_: logging.Logger | None = None,
) -> FormattingAgentResult:
    del paper_metadata  # future-compatible reserved input
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or FormattingConfig.from_settings(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())

    if paper in (None, "", {}):
        return _build_error_result(
            code="missing_cited_paper",
            message="The formatting agent requires a cited paper input.",
            trace_id=resolved_trace_id,
            details={},
        )

    try:
        parsed_paper = ResearchPaperSchema.model_validate(paper)
    except ValidationError as exc:
        return _build_error_result(
            code="invalid_cited_paper",
            message="The cited paper payload is malformed and could not be parsed.",
            trace_id=resolved_trace_id,
            details={"validation_errors": exc.errors()},
        )

    profile = resolved_config.build_profile()
    author_blocks, author_warnings = build_author_blocks(author_metadata)
    input_diagnostics = validate_input_content(
        paper=parsed_paper,
        config=resolved_config,
        author_warnings=author_warnings,
    )
    fatal_input_errors = [item for item in input_diagnostics if item.severity == "error"]
    if fatal_input_errors:
        return _build_error_result(
            code="invalid_formatting_input",
            message="The formatting agent received incomplete paper content and cannot compile it safely.",
            trace_id=resolved_trace_id,
            details={"diagnostics": [item.model_dump(mode="python") for item in input_diagnostics]},
        )

    work_dir = create_work_dir(resolved_settings, resolved_trace_id)
    context = build_document_context(
        paper=parsed_paper,
        profile=profile,
        author_blocks=author_blocks,
        figures=figures,
        tables=tables,
    )

    try:
        latex_source = render_latex_document(context=context, config=resolved_config)
        html_preview, _preview_path = generate_html_preview(
            context=context,
            config=resolved_config,
            work_dir=work_dir,
        )
        formatted_paper = await asyncio.to_thread(
            compile_latex_document,
            latex_source=latex_source,
            html_preview=html_preview,
            profile=profile,
            config=resolved_config,
            work_dir=work_dir,
        )
    except Exception as exc:
        maybe_cleanup_work_dir(
            work_dir=work_dir,
            should_cleanup=resolved_config.cleanup_workdir_on_failure,
        )
        return _build_error_result(
            code="formatting_runtime_failure",
            message="The formatting runtime failed before compilation completed.",
            trace_id=resolved_trace_id,
            details={"exception": str(exc)},
        )

    if input_diagnostics:
        formatted_paper.compile_report.diagnostics = [
            *input_diagnostics,
            *formatted_paper.compile_report.diagnostics,
        ]
        formatted_paper.compile_report.retry_recommended = (
            formatted_paper.compile_report.retry_recommended
            or any(item.retryable for item in input_diagnostics)
        )

    paper_snapshot = build_legacy_paper_snapshot(parsed_paper)
    metadata = {
        "diagnostic_summary": summarize_diagnostics(formatted_paper.compile_report.diagnostics),
        "compile_success": formatted_paper.compile_report.success,
        "retry_recommended": formatted_paper.compile_report.retry_recommended,
    }

    if formatted_paper.compile_report.success:
        maybe_cleanup_work_dir(
            work_dir=work_dir,
            should_cleanup=resolved_config.cleanup_workdir_on_success,
        )
        return FormattingAgentResult(
            formatted_paper=formatted_paper,
            paper_snapshot=paper_snapshot,
            trace_id=resolved_trace_id,
            metadata=metadata,
        )

    maybe_cleanup_work_dir(
        work_dir=work_dir,
        should_cleanup=resolved_config.cleanup_workdir_on_failure,
    )
    return FormattingAgentResult(
        formatted_paper=formatted_paper,
        paper_snapshot=paper_snapshot,
        error=FormattingAgentError(
            code="compile_failed",
            message="The IEEE manuscript did not compile successfully.",
            trace_id=resolved_trace_id,
            details={
                "compile_report": formatted_paper.compile_report.model_dump(mode="python"),
                "artifacts": formatted_paper.artifacts.model_dump(mode="python"),
            },
        ),
        trace_id=resolved_trace_id,
        metadata=metadata,
    )


if ADKBaseAgent is not None:

    class FormattingAgent(ADKBaseAgent):
        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: FormattingConfig = Field(default_factory=FormattingConfig.from_settings, exclude=True)

        def __init__(self, *, settings: Settings | None = None, config: FormattingConfig | None = None):
            resolved_settings = settings or get_settings()
            resolved_config = config or FormattingConfig.from_settings(resolved_settings)
            super().__init__(
                name="formatting_agent",
                description="Renders, compiles, validates, and previews IEEE conference manuscripts with real pdflatex.",
                settings=resolved_settings,
                config=resolved_config,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_formatting_pipeline(
                paper=state.get("paper"),
                author_metadata=state.get("author_metadata"),
                paper_metadata=state.get("paper_metadata"),
                figures=state.get("figures"),
                tables=state.get("tables"),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
            )

            if result.formatted_paper is not None:
                state["formatted_paper"] = result.formatted_paper.model_dump(mode="python")
            if result.paper_snapshot is not None:
                state["formatted_paper_snapshot"] = result.paper_snapshot.model_dump(mode="python")
            if result.error is not None:
                state["formatting_error"] = result.error.model_dump(mode="python")

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

    class FormattingAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


def build_runtime(settings: Settings | None = None, config: FormattingConfig | None = None) -> FormattingRuntime:
    resolved_settings = settings or get_settings()
    resolved_config = config or FormattingConfig.from_settings(resolved_settings)
    return FormattingRuntime(settings=resolved_settings, config=resolved_config)


def _build_error_result(
    *,
    code: str,
    message: str,
    trace_id: str,
    details: dict[str, Any],
) -> FormattingAgentResult:
    return FormattingAgentResult(
        error=FormattingAgentError(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details,
        ),
        trace_id=trace_id,
        metadata={"status": "error"},
    )


runtime = build_runtime()
if ADKBaseAgent is not None:  # pragma: no branch
    agent = FormattingAgent(settings=runtime.settings, config=runtime.config)

    try:  # pragma: no cover - optional A2A runtime wiring
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("ADK A2A bridge is unavailable: %s", exc)
        to_a2a = None

    if to_a2a is not None:  # pragma: no cover - environment dependent
        try:
            app = to_a2a(agent, public_url=os.environ.get("PUBLIC_URL"))
        except Exception as exc:
            logger.warning("Unable to build A2A app for the formatting agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the formatting agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
