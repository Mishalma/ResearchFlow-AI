from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import logging
import os
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from agents.citation_agent import CitationAgent
from agents.figure_table_agent import FigureTableAgent
from agents.humanizer_agent import HumanizerAgent
from agents.ieee_formatting_agent import IEEEFormattingAgent
from agents.originality_agent import OriginalityAgent
from agents.registry import AgentRegistry, get_agent_registry
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
from humanizer.utils import SECTION_ORDER, build_generated_paper, build_section_text_map, verify_rewrite_safety
from humanizer.agent import HumanizerRuntimeAgent
from humanizer.config import HumanizerConfig
from mcp.mcp_server import build_default_mcp_server
from models.generation import (
    AgentTiming,
    CitationAgentOutput,
    FigureTableAgentOutput,
    FormattingAgentOutput,
    GeneratedPaper,
    GenerationMetadata,
    PartialDraftPayload,
    HumanizerAgentOutput,
    OriginalityAgentOutput,
    PipelineResult,
    ResearchPaperSchema,
    SectionGateAttempt,
    SectionGateResult,
    SectionWorkflowReport,
    StructuringAgentOutput,
    WritingAgentOutput,
)
from models.validation import (
    ValidationCandidate,
    ValidationCandidateScoringConfig,
    ValidationCandidateScoringRequest,
)
from orchestration.a2a_manager import A2AManager, InProcessTransport
from structuring.schemas import StructuredPaperDraft
from writing.config import WritingConfig
from writing.diversity import HeuristicDiversityRewriter
from writing.schemas import BODY_WRITING_SECTIONS, WrittenPaperDraft, WrittenSection, build_paper_snapshot
from writing.section_writer import (
    DeterministicSectionGenerator,
    LLMSectionGenerator,
    select_title,
    write_section,
)
from writing.utils import compute_global_confidence, derive_keywords

logger = logging.getLogger("papereasy.backend.pipeline")

@dataclass
class _FormattingPhaseResult:
    resolved_settings: Settings
    registry: AgentRegistry
    vertex_client: VertexGeminiClient
    a2a_manager: A2AManager
    trace_id: str
    start_time: float
    source_text_length: int
    validation_events: list[str]
    pipeline_context: dict[str, object]
    structuring_agent: StructuringAgent
    writing_agent: WritingAgent
    figure_table_agent: FigureTableAgent
    citation_agent: CitationAgent
    formatting_agent: IEEEFormattingAgent
    structuring_result: StructuringAgentOutput
    writing_result: WritingAgentOutput
    citation_result: CitationAgentOutput
    formatting_result: FormattingAgentOutput
    structuring_duration_ms: float
    writing_duration_ms: float
    figure_table_duration_ms: float
    citation_duration_ms: float
    formatting_duration_ms: float


class _PreflightSectionCandidates(BaseModel):
    candidates: list[str] = Field(default_factory=list)


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
    max_retries = int(
            getattr(
                getattr(humanizer_agent, "humanizer_config", None),
                "max_iterations",
                5,
            )
        or 5
    )
    max_retries = max(1, min(5, max_retries))
    result = humanizer_agent.run(
        build_section_text_map(paper),
        paper=paper,
        iteration=0,
    )

    for attempt in range(1, max_retries + 1):
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
            if int(result.get("sections_rewritten") or 0) <= 0:
                logger.warning(
                    "[Humanizer] retry requested without changed sections; proceeding with best no-change result",
                )
                break
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
            max_retries,
        )

    output = humanizer_agent.build_output(
        paper=paper,
        runtime_result=result,
        trace_id=trace_id,
    )
    return HumanizerAgentOutput.model_validate(output)


def _build_generated_paper_from_formatting(
    formatting_result: FormattingAgentOutput,
) -> GeneratedPaper:
    return GeneratedPaper(
        paper=formatting_result.paper,
        formatted_text=formatting_result.formatted_text,
        latex_ready=formatting_result.latex_ready,
    )


def _build_common_metadata_fields(
    phase_result: _FormattingPhaseResult,
    *,
    total_duration_ms: float,
    validation_events: list[str],
    agent_timings: list[AgentTiming],
) -> dict[str, object]:
    return {
        "model": phase_result.resolved_settings.vertex_model,
        "generation_time_ms": total_duration_ms,
        "source_text_length": phase_result.source_text_length,
        "trace_id": phase_result.trace_id,
        "agent_timings": agent_timings,
        "mcp_tools_used": phase_result.registry.get("citation_agent").enabled_tools,
        "validation_events": validation_events,
        "structuring_global_confidence": phase_result.structuring_result.global_confidence,
        "structuring_section_confidences": phase_result.structuring_result.section_confidences,
        "structuring_evidence_summary": phase_result.structuring_result.evidence_summary,
        "writing_global_confidence": phase_result.writing_result.global_confidence,
        "writing_section_confidences": phase_result.writing_result.section_confidences,
        "writing_annotation_summary": phase_result.writing_result.annotation_summary,
        "citation_match_count": phase_result.citation_result.matched_claim_count,
        "citation_bibliography_count": phase_result.citation_result.bibliography_count,
        "citation_provider_summary": phase_result.citation_result.provider_summary,
        "figure_table_figure_count": int(phase_result.pipeline_context.get("generated_figure_count") or 0),
        "figure_table_table_count": int(phase_result.pipeline_context.get("generated_table_count") or 0),
        "formatting_compile_success": phase_result.formatting_result.compile_success,
        "formatting_retry_recommended": phase_result.formatting_result.retry_recommended,
        "formatting_diagnostic_summary": phase_result.formatting_result.diagnostic_summary,
    }


def _as_string_list(value: object, *, limit: int = 8) -> list[str]:
    if value is None:
        return []
    candidates = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = str(item).strip()
        if not text:
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        cleaned.append(text[:500])
        if len(cleaned) >= limit:
            break
    return cleaned


def _source_span_ids(value: object, *, limit: int = 12) -> list[str]:
    spans = list(value) if isinstance(value, (list, tuple)) else []
    identifiers: list[str] = []
    for span in spans:
        payload = span if isinstance(span, dict) else getattr(span, "model_dump", lambda **_: {})()
        if not isinstance(payload, dict):
            continue
        chunk_id = str(payload.get("chunk_id") or "").strip()
        start_char = payload.get("start_char")
        end_char = payload.get("end_char")
        if chunk_id and start_char is not None and end_char is not None:
            identifiers.append(f"{chunk_id}:{start_char}:{end_char}")
        if len(identifiers) >= limit:
            break
    return identifiers


def _section_payload(payload: object, section_name: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        section = payload.get(section_name)
        if isinstance(section, dict):
            return section
    return {}


def _build_remediation_context(phase_result: _FormattingPhaseResult) -> dict[str, Any]:
    structured_draft = (
        phase_result.structuring_result.structured_draft
        if isinstance(phase_result.structuring_result.structured_draft, dict)
        else {}
    )
    structured_sections = structured_draft.get("sections") if isinstance(structured_draft, dict) else {}
    evidence_notes = structured_draft.get("evidence_notes") if isinstance(structured_draft, dict) else {}
    written_draft = (
        phase_result.writing_result.written_draft
        if isinstance(phase_result.writing_result.written_draft, dict)
        else {}
    )
    written_sections = written_draft.get("sections") if isinstance(written_draft, dict) else {}
    final_section_texts = build_section_text_map(phase_result.formatting_result.paper)

    sections: dict[str, dict[str, Any]] = {}
    for section_name in SECTION_ORDER:
        skeleton = _section_payload(structured_sections, section_name)
        notes = evidence_notes.get(section_name) if isinstance(evidence_notes, dict) else []
        notes = list(notes) if isinstance(notes, (list, tuple)) else []
        note_direct: list[str] = []
        note_inferred: list[str] = []
        note_missing: list[str] = []
        note_span_ids: list[str] = []
        for raw_note in notes[:8]:
            note = raw_note if isinstance(raw_note, dict) else getattr(raw_note, "model_dump", lambda **_: {})()
            if not isinstance(note, dict):
                continue
            note_direct.extend(_as_string_list(note.get("direct_evidence"), limit=4))
            note_inferred.extend(_as_string_list(note.get("inferred_synthesis"), limit=4))
            note_missing.extend(_as_string_list(note.get("missing_information"), limit=4))
            note_span_ids.extend(_source_span_ids(note.get("source_spans"), limit=4))

        section_text = final_section_texts.get(section_name, "")
        sections[section_name] = {
            "confidence": float(phase_result.structuring_result.section_confidences.get(section_name, 0.0)),
            "draft": str(skeleton.get("draft") or "")[:1200],
            "key_points": _as_string_list(skeleton.get("key_points"), limit=8),
            "direct_evidence": _as_string_list(skeleton.get("direct_evidence"), limit=8)
            + _as_string_list(note_direct, limit=8),
            "inferred_synthesis": _as_string_list(skeleton.get("inferred_synthesis"), limit=8)
            + _as_string_list(note_inferred, limit=8),
            "missing_evidence": _as_string_list(skeleton.get("missing_evidence"), limit=6)
            + _as_string_list(note_missing, limit=6),
            "source_span_ids": _source_span_ids(skeleton.get("source_spans"), limit=12)
            + _as_string_list(note_span_ids, limit=12),
            "citation_map": re.findall(r"\[[0-9,\-\s]+\]|\\cite[t|p]?\{[^}]+\}", section_text),
            "written_claims": _as_string_list(
                (_section_payload(written_sections, section_name) or {}).get("claims"),
                limit=8,
            ),
        }

    return {
        "schema_version": "1.0.0",
        "trace_id": phase_result.trace_id,
        "source_text_length": phase_result.source_text_length,
        "sections": sections,
        "references": list(phase_result.formatting_result.paper.references),
    }


def _build_remediation_context_from_structuring(
    *,
    structuring_result: StructuringAgentOutput,
    trace_id: str,
    source_text_length: int,
    accepted_sections: dict[str, str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    structured_draft = (
        structuring_result.structured_draft
        if isinstance(structuring_result.structured_draft, dict)
        else {}
    )
    structured_sections = structured_draft.get("sections") if isinstance(structured_draft, dict) else {}
    evidence_notes = structured_draft.get("evidence_notes") if isinstance(structured_draft, dict) else {}
    accepted_sections = accepted_sections or {}

    sections: dict[str, dict[str, Any]] = {}
    for section_name in SECTION_ORDER:
        skeleton = _section_payload(structured_sections, section_name)
        notes = evidence_notes.get(section_name) if isinstance(evidence_notes, dict) else []
        notes = list(notes) if isinstance(notes, (list, tuple)) else []
        note_direct: list[str] = []
        note_inferred: list[str] = []
        note_missing: list[str] = []
        note_span_ids: list[str] = []
        for raw_note in notes[:8]:
            note = raw_note if isinstance(raw_note, dict) else getattr(raw_note, "model_dump", lambda **_: {})()
            if not isinstance(note, dict):
                continue
            note_direct.extend(_as_string_list(note.get("direct_evidence"), limit=4))
            note_inferred.extend(_as_string_list(note.get("inferred_synthesis"), limit=4))
            note_missing.extend(_as_string_list(note.get("missing_information"), limit=4))
            note_span_ids.extend(_source_span_ids(note.get("source_spans"), limit=4))

        section_text = accepted_sections.get(section_name, "")
        sections[section_name] = {
            "confidence": float(structuring_result.section_confidences.get(section_name, 0.0)),
            "draft": str(skeleton.get("draft") or "")[:1200],
            "key_points": _as_string_list(skeleton.get("key_points"), limit=8),
            "direct_evidence": _as_string_list(skeleton.get("direct_evidence"), limit=8)
            + _as_string_list(note_direct, limit=8),
            "inferred_synthesis": _as_string_list(skeleton.get("inferred_synthesis"), limit=8)
            + _as_string_list(note_inferred, limit=8),
            "missing_evidence": _as_string_list(skeleton.get("missing_evidence"), limit=6)
            + _as_string_list(note_missing, limit=6),
            "source_span_ids": _source_span_ids(skeleton.get("source_spans"), limit=12)
            + _as_string_list(note_span_ids, limit=12),
            "citation_map": re.findall(r"\[[0-9,\-\s]+\]|\\cite[t|p]?\{[^}]+\}", section_text),
            "written_claims": [],
        }

    return {
        "schema_version": "1.0.0",
        "trace_id": trace_id,
        "source_text_length": source_text_length,
        "sections": sections,
        "references": list(references or []),
    }


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 8) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def _env_float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    values = tuple(item.strip() for item in re.split(r"[,;|]", raw) if item.strip())
    return values or default


def _section_gate_order() -> tuple[str, ...]:
    default_order = (*BODY_WRITING_SECTIONS, "abstract")
    configured_order = _env_csv("SECTION_GATE_ORDER", default_order)
    allowed = set(SECTION_ORDER)
    ordered: list[str] = []
    for section_name in configured_order:
        normalized = section_name.strip().lower()
        if normalized in allowed and normalized not in ordered:
            ordered.append(normalized)
    for section_name in default_order:
        if section_name not in ordered:
            ordered.append(section_name)
    return tuple(ordered)


def _section_gate_timeout_seconds() -> int:
    return _env_int("SECTION_GATE_MODEL_TIMEOUT_SECONDS", 45, minimum=5, maximum=180)


def _section_gate_timeout_for_section(section_name: str, default_timeout: int) -> int:
    if section_name == "abstract":
        return _env_int(
            "SECTION_GATE_ABSTRACT_TIMEOUT_SECONDS",
            max(default_timeout, 75),
            minimum=5,
            maximum=180,
        )
    return default_timeout


def _section_gate_writing_candidate_count(section_name: str, default_count: int) -> int:
    if section_name == "abstract":
        return _env_int(
            "SECTION_GATE_ABSTRACT_WRITING_CANDIDATES",
            max(default_count, 4),
            minimum=1,
            maximum=6,
        )
    return default_count


def _section_gate_humanizer_candidate_count(section_name: str) -> int:
    default_count = _env_int("SECTION_GATE_HUMANIZER_CANDIDATES", 2, minimum=1, maximum=6)
    if section_name == "abstract":
        return _env_int(
            "SECTION_GATE_ABSTRACT_HUMANIZER_CANDIDATES",
            max(default_count, 4),
            minimum=1,
            maximum=6,
        )
    return default_count


def _compact_previous_section_context(accepted_sections: dict[str, str]) -> str:
    snippets: list[str] = []
    for section_name in SECTION_ORDER:
        text = accepted_sections.get(section_name, "").strip()
        if not text:
            continue
        snippets.append(f"{section_name}: {text[:420]}")
    return "\n".join(snippets[-3:])


def _section_gate_failure_reasons(results: object) -> list[str]:
    reasons: list[str] = []
    for result in list(results or []):
        for reason in getattr(result, "rejection_reasons", []) or []:
            cleaned = str(reason).strip()
            if cleaned and cleaned not in reasons:
                reasons.append(cleaned)
    return reasons


def _best_ai_score(results: object) -> float | None:
    scores = [
        float(getattr(result, "ai_score"))
        for result in list(results or [])
        if getattr(result, "ai_score", None) is not None
    ]
    return min(scores) if scores else None


def _select_scored_candidate(
    *,
    candidates: dict[str, str],
    scoring_results: object,
    require_accepted: bool = True,
) -> tuple[str | None, str | None, float | None]:
    results = list(scoring_results or [])
    if require_accepted:
        results = [result for result in results if bool(getattr(result, "accepted", False))]
    if not results:
        return None, None, None
    results.sort(
        key=lambda item: (
            float(getattr(item, "ai_score", 1.0) if getattr(item, "ai_score", None) is not None else 1.0),
            str(getattr(item, "candidate_id", "")),
        )
    )
    selected = results[0]
    candidate_id = str(getattr(selected, "candidate_id", "")).strip()
    return candidate_id, candidates.get(candidate_id), getattr(selected, "ai_score", None)


async def _score_section_gate_candidates(
    *,
    validation_client: Any,
    job_id: str,
    project_id: str,
    user_id: str,
    trace_id: str,
    section_name: str,
    source_text: str,
    candidates: dict[str, str],
) -> Any:
    return await validation_client.score_candidates(
        ValidationCandidateScoringRequest(
            task_id=f"section-gate-score-{job_id}-{section_name}",
            job_id=job_id or f"local-{trace_id[:12]}",
            project_id=project_id or "unknown-project",
            user_id=user_id or "unknown-user",
            idempotency_key=f"section-gate-{trace_id[:16]}",
            source_text=source_text,
            candidates=[
                ValidationCandidate(
                    candidate_id=candidate_id,
                    section_id=section_name,
                    text=text,
                )
                for candidate_id, text in candidates.items()
                if text.strip()
            ],
            config=ValidationCandidateScoringConfig(
                compute_overlap=False,
                accept_mode="ai_only",
                ai_accept_threshold=_env_float("SECTION_GATE_AI_THRESHOLD", 0.10),
            ),
        )
    )


async def _write_section_candidates_for_gate(
    *,
    section_name: str,
    skeleton: Any,
    config: WritingConfig,
    vertex_client: VertexGeminiClient,
    paper_topic: str,
    paper_domain: str,
    author_metadata: str,
    writing_style_preferences: str,
    accepted_sections: dict[str, str],
    candidate_count: int,
    timeout_seconds: int,
) -> list[tuple[str, WrittenSection, str]]:
    llm_generator = LLMSectionGenerator(client=vertex_client, config=config) if config.use_model_generator else None
    deterministic_generator = DeterministicSectionGenerator()
    diversity_rewriter = HeuristicDiversityRewriter() if config.enable_diversity_pass else None
    previous_context = _compact_previous_section_context(accepted_sections)
    style_variants = (
        "Use an evidence-led opening and avoid stock academic transitions.",
        "Use a problem-specific opening and vary sentence length more strongly.",
        "Use a restrained, researcher-like cadence with concrete nouns.",
        "Use synthesis-first prose and avoid mirroring the source wording.",
    )
    candidates: list[tuple[str, WrittenSection, str]] = []
    seen: set[str] = set()

    for index in range(1, max(1, candidate_count) + 1):
        variant = style_variants[(index - 1) % len(style_variants)]
        contextual_preferences = (
            f"{writing_style_preferences}\n"
            f"Section gate candidate {index}: {variant}\n"
            "Write as if this section must pass an academic AI detector without losing scholarly precision.\n"
            "Prefer source-grounded specificity, measured uncertainty, and non-repetitive sentence openings."
        ).strip()
        if previous_context:
            contextual_preferences = (
                f"{contextual_preferences}\n"
                "Already accepted earlier sections, for continuity only:\n"
                f"{previous_context}"
            )
        try:
            written_section, _bundle, backend = await asyncio.wait_for(
                write_section(
                    section_name=section_name,
                    skeleton=skeleton,
                    config=config,
                    context={
                        "paper_topic": paper_topic,
                        "paper_domain": paper_domain,
                        "author_metadata": author_metadata,
                        "writing_style_preferences": contextual_preferences,
                        "config": config,
                    },
                    llm_generator=llm_generator,
                    deterministic_generator=deterministic_generator,
                    diversity_rewriter=diversity_rewriter,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Section gate writing timed out for %s candidate %s.", section_name, index)
            continue
        except Exception as exc:
            logger.warning("Section gate writing failed for %s candidate %s: %s", section_name, index, exc)
            continue

        text = written_section.text.strip()
        folded = text.casefold()
        if not text or folded in seen:
            continue
        seen.add(folded)
        candidates.append((f"{section_name}-writing-{index}", written_section, backend))

    return candidates


async def _humanize_section_candidate_for_gate(
    *,
    section_name: str,
    base_text: str,
    remediation_context: dict[str, Any],
    strategy: str,
    strategy_index: int,
    settings: Settings,
    timeout_seconds: int,
    candidate_count: int,
) -> tuple[str | None, dict[str, Any]]:
    humanizer_config = replace(
        HumanizerConfig.from_settings(settings),
        full_section_rewrite=True,
        section_rewrite_candidate_count=max(1, min(6, int(candidate_count or 1))),
        strategy_order=(strategy,),
        max_iterations=1,
        max_runtime_seconds=timeout_seconds,
        use_desklib_candidate_scoring=False,
        require_desklib_candidate_improvement=False,
    )
    runtime = HumanizerRuntimeAgent(config=humanizer_config, settings=settings)

    try:
        runtime_result = await asyncio.wait_for(
            asyncio.to_thread(
                runtime.run,
                {section_name: base_text},
                strategy_index,
                target_sections={section_name},
                remediation_context=remediation_context,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        return None, {
            "failure_reasons": ["humanizer_timeout"],
            "candidate_count": 0,
            "rewriter_mode": "none",
        }
    except Exception as exc:
        logger.warning("Section gate humanizer failed for %s strategy %s: %s", section_name, strategy, exc)
        return None, {
            "failure_reasons": ["humanizer_failed"],
            "candidate_count": 0,
            "rewriter_mode": "none",
        }

    candidate = str((runtime_result.get("updated_sections") or {}).get(section_name) or "").strip()
    if not candidate or candidate == base_text.strip():
        return None, runtime_result
    return candidate, runtime_result


def _build_written_section_from_text(
    *,
    section_name: str,
    text: str,
    confidence: float,
    revision_notes: list[str],
) -> WrittenSection:
    return WrittenSection(
        section_name=section_name,
        text=text,
        confidence=max(0.0, min(1.0, float(confidence))),
        revision_notes=revision_notes,
    )


def _build_preflight_prompt(
    *,
    section_name: str,
    section_text: str,
    remediation_context: dict[str, Any],
    candidate_count: int,
) -> str:
    context_payload = json_safe_section_context(remediation_context, section_name=section_name)
    return (
        "Create alternative versions of one academic manuscript section from evidence notes.\n"
        "Do not copy source phrasing closely. Do not add unsupported claims. Preserve citations, numbers, "
        "percentages, equations, LaTeX, dataset names, model names, and technical entities exactly.\n"
        f"Return exactly {candidate_count} candidates as JSON matching this schema: "
        '{"candidates":["full section text"]}.\n\n'
        f"SECTION: {section_name}\n"
        f"EVIDENCE CONTEXT:\n{context_payload}\n\n"
        f"CURRENT SECTION:\n{section_text[:6500]}"
    )


def json_safe_section_context(remediation_context: dict[str, Any], *, section_name: str) -> str:
    sections = remediation_context.get("sections") if isinstance(remediation_context, dict) else {}
    section_payload = sections.get(section_name) if isinstance(sections, dict) else {}
    if not isinstance(section_payload, dict):
        return "{}"
    compact = {
        "key_points": section_payload.get("key_points") or [],
        "direct_evidence": section_payload.get("direct_evidence") or [],
        "inferred_synthesis": section_payload.get("inferred_synthesis") or [],
        "missing_evidence": section_payload.get("missing_evidence") or [],
        "source_span_ids": section_payload.get("source_span_ids") or [],
        "citation_map": section_payload.get("citation_map") or [],
    }
    import json

    return json.dumps(compact, ensure_ascii=True)


async def _generate_preflight_candidates(
    *,
    phase_result: _FormattingPhaseResult,
    section_name: str,
    section_text: str,
    remediation_context: dict[str, Any],
    candidate_count: int,
) -> list[str]:
    prompt = _build_preflight_prompt(
        section_name=section_name,
        section_text=section_text,
        remediation_context=remediation_context,
        candidate_count=candidate_count,
    )
    result = await phase_result.vertex_client.generate_json(
        prompt=prompt,
        response_schema=_PreflightSectionCandidates,
    )
    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in result.candidates:
        text = str(candidate or "").strip()
        if not text or text == section_text.strip():
            continue
        safety = verify_rewrite_safety(
            original=section_text,
            rewritten=text,
            similarity_threshold=0.45,
        )
        if not safety.passed:
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        candidates.append(text)
    return candidates[:candidate_count]


async def _run_generation_preflight(
    *,
    generated_paper: GeneratedPaper,
    phase_result: _FormattingPhaseResult,
    remediation_context: dict[str, Any],
    source_text: str,
    job_id: str,
    project_id: str,
    user_id: str,
) -> GeneratedPaper:
    if not _env_bool("GENERATION_PREFLIGHT_SCORING", False):
        return generated_paper
    if not job_id or not user_id:
        logger.warning("Generation preflight skipped because job_id or user_id is missing.")
        return generated_paper

    candidate_count = _env_int("GENERATION_PREFLIGHT_CANDIDATES", 4, minimum=1, maximum=6)
    try:
        from app.services.validation_service import get_validation_service_client

        validation_client = get_validation_service_client(settings=phase_result.resolved_settings)
    except Exception as exc:
        logger.warning("Generation preflight skipped because validation scoring is unavailable: %s", exc)
        return generated_paper
    section_texts = build_section_text_map(generated_paper.paper)
    updated_sections = dict(section_texts)
    changed_sections: list[str] = []

    for section_name in SECTION_ORDER:
        original_text = section_texts.get(section_name, "").strip()
        if len(original_text.split()) < 35:
            continue
        try:
            candidates = await _generate_preflight_candidates(
                phase_result=phase_result,
                section_name=section_name,
                section_text=original_text,
                remediation_context=remediation_context,
                candidate_count=candidate_count,
            )
            if not candidates:
                continue
            scoring_response = await validation_client.score_candidates(
                ValidationCandidateScoringRequest(
                    task_id=f"generation-preflight-{job_id}-{section_name}",
                    job_id=job_id,
                    project_id=project_id or "unknown-project",
                    user_id=user_id,
                    idempotency_key=f"preflight-{phase_result.trace_id[:16]}",
                    source_text=source_text,
                    candidates=[
                        ValidationCandidate(
                            candidate_id=f"{section_name}-{index}",
                            section_id=section_name,
                            text=candidate,
                            original_text=original_text,
                        )
                        for index, candidate in enumerate(candidates, start=1)
                    ],
                )
            )
            accepted = [
                result for result in scoring_response.results if result.accepted and result.ai_score is not None
            ]
            if not accepted:
                continue
            accepted.sort(key=lambda item: (float(item.ai_score or 1.0), float(item.overlap_score)))
            best_candidate_id = accepted[0].candidate_id
            best_index = int(best_candidate_id.rsplit("-", 1)[-1]) - 1
            if 0 <= best_index < len(candidates):
                updated_sections[section_name] = candidates[best_index]
                changed_sections.append(section_name)
        except Exception as exc:
            logger.warning("Generation preflight skipped section %s after scoring/generation failure: %s", section_name, exc)
            continue

    if not changed_sections:
        return generated_paper

    logger.info(
        "Generation preflight accepted candidates for %s section(s).",
        len(changed_sections),
    )
    return build_generated_paper(
        source_paper=generated_paper.paper,
        section_texts=updated_sections,
    )


async def _run_section_gated_generation_pipeline(
    text: str,
    settings: Settings | None = None,
    *,
    project_id: str = "",
    job_id: str = "",
    user_id: str = "",
) -> PipelineResult:
    resolved_settings = settings or get_settings()
    trace_id = str(uuid4())
    start_time = perf_counter()
    validation_events: list[str] = []
    pipeline_context: dict[str, object] = {"section_gate_enabled": True}
    section_gate_order = _section_gate_order()

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

    for agent in [
        structuring_agent,
        figure_table_agent,
        citation_agent,
        formatting_agent,
    ]:
        a2a_manager.register(agent)

    logger.info("Section-gated pipeline trace %s started with %s source characters", trace_id, len(text))

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

    try:
        structured_draft = StructuredPaperDraft.model_validate(structuring_result.structured_draft)
    except Exception as exc:
        logger.warning("Section-gated pipeline cannot parse structured draft: %s", exc)
        workflow = SectionWorkflowReport(
            status="partial_manual_review",
            section_order=list(section_gate_order),
            accepted_sections=[],
            failed_section=section_gate_order[0],
            stop_reason="invalid_structured_draft",
            sections=[
                SectionGateResult(
                    section_name=section_gate_order[0],
                    status="failed",
                    failure_reasons=["invalid_structured_draft"],
                )
            ],
            total_duration_ms=(perf_counter() - start_time) * 1000,
        )
        partial = PartialDraftPayload(
            job_id=job_id or f"local-{trace_id[:12]}",
            project_id=project_id or "unknown-project",
            failed_section=section_gate_order[0],
            stop_reason="invalid_structured_draft",
            accepted_sections={},
            section_workflow=workflow,
        )
        metadata = GenerationMetadata(
            model=resolved_settings.vertex_model,
            generation_time_ms=(perf_counter() - start_time) * 1000,
            source_text_length=len(text),
            trace_id=trace_id,
            agent_timings=[
                AgentTiming(
                    agent=structuring_agent.agent_name,
                    duration_ms=structuring_dispatch.duration_ms,
                )
            ],
            mcp_tools_used=registry.get("citation_agent").enabled_tools,
            validation_events=validation_events + ["section_gate: stopped because structured draft was unavailable"],
            structuring_global_confidence=structuring_result.global_confidence,
            structuring_section_confidences=structuring_result.section_confidences,
            structuring_evidence_summary=structuring_result.evidence_summary,
            generation_status="partial_manual_review",
            section_gate_enabled=True,
            section_gate_failed_section=section_gate_order[0],
            section_gate_stop_reason="invalid_structured_draft",
            section_gate_accepted_sections=[],
        )
        return PipelineResult(
            generated_paper=None,
            metadata=metadata,
            remediation_context=_build_remediation_context_from_structuring(
                structuring_result=structuring_result,
                trace_id=trace_id,
                source_text_length=len(text),
            ),
            generation_status="partial_manual_review",
            section_workflow=workflow,
            partial_draft=partial,
        )

    try:
        from app.services.validation_service import get_validation_service_client

        validation_client = get_validation_service_client(settings=resolved_settings)
    except Exception as exc:
        logger.warning("Section-gated pipeline cannot initialize validation scoring: %s", exc)
        raise

    writing_config = WritingConfig.from_settings(resolved_settings)
    writing_candidate_count = _env_int("SECTION_GATE_WRITING_CANDIDATES", 2, minimum=1, maximum=4)
    timeout_seconds = _section_gate_timeout_seconds()
    strategies = _env_csv("SECTION_GATE_STRATEGIES", ("evidence_section", "detector_feedback"))[:2]
    paper_topic = structuring_result.title
    paper_domain = ", ".join(structuring_result.keywords[:5])
    author_metadata = ""
    writing_style_preferences = "Natural, source-grounded IEEE academic prose."

    accepted_sections: dict[str, str] = {}
    written_sections: dict[str, WrittenSection] = {}
    section_results: list[SectionGateResult] = []
    writing_duration_started = perf_counter()

    for section_name in section_gate_order:
        section_started = perf_counter()
        section_timeout_seconds = _section_gate_timeout_for_section(section_name, timeout_seconds)
        skeleton = structured_draft.sections[section_name]
        attempts: list[SectionGateAttempt] = []
        section_accepted = False
        accepted_source: str | None = None
        accepted_strategy: str | None = None
        accepted_candidate_id: str | None = None
        accepted_ai_score: float | None = None
        best_candidate_text: str | None = None
        failure_reasons: list[str] = []

        writing_started = perf_counter()
        writing_candidates = await _write_section_candidates_for_gate(
            section_name=section_name,
            skeleton=skeleton,
            config=writing_config,
            vertex_client=vertex_client,
            paper_topic=paper_topic,
            paper_domain=paper_domain,
            author_metadata=author_metadata,
            writing_style_preferences=writing_style_preferences,
            accepted_sections=accepted_sections,
            candidate_count=_section_gate_writing_candidate_count(section_name, writing_candidate_count),
            timeout_seconds=section_timeout_seconds,
        )
        writing_candidate_map = {
            candidate_id: written_section.text
            for candidate_id, written_section, _backend in writing_candidates
        }
        if writing_candidate_map:
            scoring_response = await _score_section_gate_candidates(
                validation_client=validation_client,
                job_id=job_id,
                project_id=project_id,
                user_id=user_id,
                trace_id=trace_id,
                section_name=section_name,
                source_text=text,
                candidates=writing_candidate_map,
            )
            selected_id, selected_text, selected_score = _select_scored_candidate(
                candidates=writing_candidate_map,
                scoring_results=scoring_response.results,
            )
            best_id, best_text, _best_score = _select_scored_candidate(
                candidates=writing_candidate_map,
                scoring_results=scoring_response.results,
                require_accepted=False,
            )
            best_candidate_text = best_text
            attempts.append(
                SectionGateAttempt(
                    section_name=section_name,
                    source="writing",
                    candidate_count=len(writing_candidate_map),
                    accepted=selected_text is not None,
                    accepted_candidate_id=selected_id,
                    best_ai_score=_best_ai_score(scoring_response.results),
                    rejection_reasons=_section_gate_failure_reasons(scoring_response.results),
                    duration_ms=(perf_counter() - writing_started) * 1000,
                )
            )
            if selected_text is not None and selected_id is not None:
                accepted_section = next(
                    (
                        written_section
                        for candidate_id, written_section, _backend in writing_candidates
                        if candidate_id == selected_id
                    ),
                    None,
                )
                if accepted_section is not None:
                    written_sections[section_name] = accepted_section
                else:
                    written_sections[section_name] = _build_written_section_from_text(
                        section_name=section_name,
                        text=selected_text,
                        confidence=skeleton.confidence,
                        revision_notes=["Accepted by section-gated AI check."],
                    )
                accepted_sections[section_name] = selected_text
                section_accepted = True
                accepted_source = "writing"
                accepted_candidate_id = selected_id
                accepted_ai_score = selected_score
            else:
                failure_reasons.extend(_section_gate_failure_reasons(scoring_response.results))
                if best_id:
                    logger.info("Section gate selected %s as remediation seed for %s.", best_id, section_name)
        else:
            failure_reasons.append("writing_generation_failed")
            attempts.append(
                SectionGateAttempt(
                    section_name=section_name,
                    source="writing",
                    candidate_count=0,
                    accepted=False,
                    rejection_reasons=["writing_generation_failed"],
                    duration_ms=(perf_counter() - writing_started) * 1000,
                )
            )

        if not section_accepted:
            base_text = best_candidate_text or str(skeleton.draft or "").strip()
            remediation_context = _build_remediation_context_from_structuring(
                structuring_result=structuring_result,
                trace_id=trace_id,
                source_text_length=len(text),
                accepted_sections={**accepted_sections, section_name: base_text},
                references=structuring_result.references,
            )
            for strategy_index, strategy in enumerate(strategies, start=1):
                humanizer_started = perf_counter()
                humanized_text, runtime_result = await _humanize_section_candidate_for_gate(
                    section_name=section_name,
                    base_text=base_text,
                    remediation_context=remediation_context,
                    strategy=strategy,
                    strategy_index=strategy_index,
                    settings=resolved_settings,
                    timeout_seconds=section_timeout_seconds,
                    candidate_count=_section_gate_humanizer_candidate_count(section_name),
                )
                if not humanized_text:
                    reasons = list(runtime_result.get("failure_reasons", [])) or ["humanizer_no_change"]
                    attempts.append(
                        SectionGateAttempt(
                            section_name=section_name,
                            source="humanizer",
                            strategy=strategy,
                            candidate_count=int(runtime_result.get("candidate_count") or 0),
                            accepted=False,
                            rejection_reasons=reasons,
                            duration_ms=(perf_counter() - humanizer_started) * 1000,
                        )
                    )
                    failure_reasons.extend([reason for reason in reasons if reason not in failure_reasons])
                    continue

                candidate_id = f"{section_name}-humanizer-{strategy_index}"
                scoring_response = await _score_section_gate_candidates(
                    validation_client=validation_client,
                    job_id=job_id,
                    project_id=project_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    section_name=section_name,
                    source_text=text,
                    candidates={candidate_id: humanized_text},
                )
                selected_id, selected_text, selected_score = _select_scored_candidate(
                    candidates={candidate_id: humanized_text},
                    scoring_results=scoring_response.results,
                )
                reasons = _section_gate_failure_reasons(scoring_response.results)
                attempts.append(
                    SectionGateAttempt(
                        section_name=section_name,
                        source="humanizer",
                        strategy=strategy,
                        candidate_count=int(runtime_result.get("candidate_count") or 1),
                        accepted=selected_text is not None,
                        accepted_candidate_id=selected_id,
                        best_ai_score=_best_ai_score(scoring_response.results),
                        rejection_reasons=reasons,
                        duration_ms=(perf_counter() - humanizer_started) * 1000,
                    )
                )
                if selected_text is not None and selected_id is not None:
                    written_sections[section_name] = _build_written_section_from_text(
                        section_name=section_name,
                        text=selected_text,
                        confidence=skeleton.confidence,
                        revision_notes=[
                            f"Accepted after section-gated humanizer strategy '{strategy}'."
                        ],
                    )
                    accepted_sections[section_name] = selected_text
                    section_accepted = True
                    accepted_source = "humanizer"
                    accepted_strategy = strategy
                    accepted_candidate_id = selected_id
                    accepted_ai_score = selected_score
                    break
                failure_reasons.extend([reason for reason in reasons if reason not in failure_reasons])

        if section_accepted:
            section_results.append(
                SectionGateResult(
                    section_name=section_name,
                    status="accepted",
                    accepted_source=accepted_source,
                    accepted_strategy=accepted_strategy,
                    accepted_candidate_id=accepted_candidate_id,
                    final_ai_score=accepted_ai_score,
                    attempts=attempts,
                    duration_ms=(perf_counter() - section_started) * 1000,
                    failure_reasons=[],
                )
            )
            validation_events.append(f"section_gate:{section_name} accepted via {accepted_source}")
            continue

        normalized_reasons = failure_reasons or ["section_gate_no_passing_candidate"]
        section_results.append(
            SectionGateResult(
                section_name=section_name,
                status="failed",
                attempts=attempts,
                duration_ms=(perf_counter() - section_started) * 1000,
                failure_reasons=normalized_reasons,
            )
        )
        workflow = SectionWorkflowReport(
            status="partial_manual_review",
            section_order=list(section_gate_order),
            accepted_sections=list(accepted_sections.keys()),
            failed_section=section_name,
            stop_reason=normalized_reasons[0],
            sections=section_results,
            total_duration_ms=(perf_counter() - writing_duration_started) * 1000,
        )
        partial = PartialDraftPayload(
            job_id=job_id or f"local-{trace_id[:12]}",
            project_id=project_id or "unknown-project",
            failed_section=section_name,
            stop_reason=normalized_reasons[0],
            accepted_sections=accepted_sections,
            failed_section_candidate=best_candidate_text,
            section_workflow=workflow,
        )
        total_duration_ms = (perf_counter() - start_time) * 1000
        metadata = GenerationMetadata(
            model=resolved_settings.vertex_model,
            generation_time_ms=total_duration_ms,
            source_text_length=len(text),
            trace_id=trace_id,
            agent_timings=[
                AgentTiming(
                    agent=structuring_agent.agent_name,
                    duration_ms=structuring_dispatch.duration_ms,
                ),
                AgentTiming(
                    agent=writing_agent.agent_name,
                    duration_ms=(perf_counter() - writing_duration_started) * 1000,
                ),
            ],
            mcp_tools_used=registry.get("citation_agent").enabled_tools,
            validation_events=validation_events
            + [f"section_gate:{section_name} stopped early ({normalized_reasons[0]})"],
            structuring_global_confidence=structuring_result.global_confidence,
            structuring_section_confidences=structuring_result.section_confidences,
            structuring_evidence_summary=structuring_result.evidence_summary,
            writing_global_confidence=compute_global_confidence(
                [section.confidence for section in written_sections.values()]
            )
            if written_sections
            else None,
            writing_section_confidences={
                name: section.confidence for name, section in written_sections.items()
            },
            writing_annotation_summary={},
            generation_status="partial_manual_review",
            section_gate_enabled=True,
            section_gate_failed_section=section_name,
            section_gate_stop_reason=normalized_reasons[0],
            section_gate_accepted_sections=list(accepted_sections.keys()),
        )
        return PipelineResult(
            generated_paper=None,
            metadata=metadata,
            remediation_context=_build_remediation_context_from_structuring(
                structuring_result=structuring_result,
                trace_id=trace_id,
                source_text_length=len(text),
                accepted_sections=accepted_sections,
                references=structuring_result.references,
            ),
            generation_status="partial_manual_review",
            section_workflow=workflow,
            partial_draft=partial,
        )

    writing_duration_ms = (perf_counter() - writing_duration_started) * 1000
    title, title_notes, title_backend = await select_title(
        structured_draft=structured_draft,
        config=writing_config,
        vertex_client=vertex_client,
        paper_topic=paper_topic,
        paper_domain=paper_domain,
    )
    body_sections = {
        section_name: written_sections[section_name]
        for section_name in BODY_WRITING_SECTIONS
    }
    keywords = derive_keywords(
        title=title,
        abstract_text=written_sections["abstract"].text,
        section_texts=[section.text for section in body_sections.values()],
        paper_domain=paper_domain,
        fallback_keywords=structuring_result.keywords,
    )
    written_draft = WrittenPaperDraft(
        title=title,
        abstract=written_sections["abstract"],
        sections=body_sections,
        global_confidence=compute_global_confidence(
            [section.confidence for section in written_sections.values()]
        ),
        metadata={
            "trace_id": trace_id,
            "title_notes": title_notes,
            "generation_backends": {"title": title_backend, "sections": "section_gate"},
            "keywords": keywords,
            "annotation_summary": {},
            "fallback_references": list(structuring_result.references),
            "section_gate": True,
        },
    )
    paper_snapshot = build_paper_snapshot(
        title=written_draft.title,
        abstract=written_draft.abstract.text,
        keywords=keywords,
        sections=written_draft.sections,
        references=list(structuring_result.references),
    )
    writing_result = WritingAgentOutput(
        title=paper_snapshot.title,
        abstract=paper_snapshot.abstract,
        keywords=paper_snapshot.keywords,
        sections=paper_snapshot.sections,
        references=paper_snapshot.references,
        written_draft=written_draft.model_dump(mode="python"),
        global_confidence=written_draft.global_confidence,
        section_confidences={
            "abstract": written_draft.abstract.confidence,
            **{
                section_name: section.confidence
                for section_name, section in written_draft.sections.items()
            },
        },
        annotation_summary={},
        trace_id=trace_id,
        error=None,
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

    phase_result = _FormattingPhaseResult(
        resolved_settings=resolved_settings,
        registry=registry,
        vertex_client=vertex_client,
        a2a_manager=a2a_manager,
        trace_id=trace_id,
        start_time=start_time,
        source_text_length=len(text),
        validation_events=validation_events,
        pipeline_context=pipeline_context,
        structuring_agent=structuring_agent,
        writing_agent=writing_agent,
        figure_table_agent=figure_table_agent,
        citation_agent=citation_agent,
        formatting_agent=formatting_agent,
        structuring_result=structuring_result,
        writing_result=writing_result,
        citation_result=citation_result,
        formatting_result=formatting_result,
        structuring_duration_ms=structuring_dispatch.duration_ms,
        writing_duration_ms=writing_duration_ms,
        figure_table_duration_ms=figure_table_duration_ms,
        citation_duration_ms=citation_dispatch.duration_ms,
        formatting_duration_ms=formatting_dispatch.duration_ms,
    )
    total_duration_ms = (perf_counter() - start_time) * 1000
    workflow = SectionWorkflowReport(
        status="completed",
        section_order=list(section_gate_order),
        accepted_sections=list(accepted_sections.keys()),
        failed_section=None,
        stop_reason=None,
        sections=section_results,
        total_duration_ms=writing_duration_ms,
    )
    validation_events = list(phase_result.validation_events)
    validation_events.append("section_gate: all text sections passed AI-only Desklib gate")
    validation_events.append("pipeline: formatting boundary reached; humanizer/originality deferred")
    metadata = GenerationMetadata(
        **_build_common_metadata_fields(
            phase_result,
            total_duration_ms=total_duration_ms,
            validation_events=validation_events,
            agent_timings=[
                AgentTiming(
                    agent=structuring_agent.agent_name,
                    duration_ms=structuring_dispatch.duration_ms,
                ),
                AgentTiming(
                    agent=writing_agent.agent_name,
                    duration_ms=writing_duration_ms,
                ),
                AgentTiming(
                    agent=figure_table_agent.agent_name,
                    duration_ms=figure_table_duration_ms,
                ),
                AgentTiming(
                    agent=citation_agent.agent_name,
                    duration_ms=citation_dispatch.duration_ms,
                ),
                AgentTiming(
                    agent=formatting_agent.agent_name,
                    duration_ms=formatting_dispatch.duration_ms,
                ),
            ],
        ),
        generation_status="completed",
        section_gate_enabled=True,
        section_gate_failed_section=None,
        section_gate_stop_reason=None,
        section_gate_accepted_sections=list(accepted_sections.keys()),
    )
    remediation_context = _build_remediation_context(phase_result)
    logger.info(
        "Section-gated pipeline trace %s reached formatting boundary in %.2f ms",
        trace_id,
        total_duration_ms,
    )
    return PipelineResult(
        generated_paper=_build_generated_paper_from_formatting(formatting_result),
        metadata=metadata,
        generated_figures=pipeline_context.get("generated_figures"),
        generated_tables=pipeline_context.get("generated_tables"),
        figure_table_status=pipeline_context.get("figure_table_status"),
        figure_table_error=pipeline_context.get("figure_table_error"),
        remediation_context=remediation_context,
        generation_status="completed",
        section_workflow=workflow,
        partial_draft=None,
    )


async def _run_pipeline_until_formatting(
    text: str,
    settings: Settings | None = None,
    *,
    project_id: str = "",
) -> _FormattingPhaseResult:
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

    for agent in [
        structuring_agent,
        writing_agent,
        figure_table_agent,
        citation_agent,
        formatting_agent,
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

    return _FormattingPhaseResult(
        resolved_settings=resolved_settings,
        registry=registry,
        vertex_client=vertex_client,
        a2a_manager=a2a_manager,
        trace_id=trace_id,
        start_time=start_time,
        source_text_length=len(text),
        validation_events=validation_events,
        pipeline_context=pipeline_context,
        structuring_agent=structuring_agent,
        writing_agent=writing_agent,
        figure_table_agent=figure_table_agent,
        citation_agent=citation_agent,
        formatting_agent=formatting_agent,
        structuring_result=structuring_result,
        writing_result=writing_result,
        citation_result=citation_result,
        formatting_result=formatting_result,
        structuring_duration_ms=structuring_dispatch.duration_ms,
        writing_duration_ms=writing_dispatch.duration_ms,
        figure_table_duration_ms=figure_table_duration_ms,
        citation_duration_ms=citation_dispatch.duration_ms,
        formatting_duration_ms=formatting_dispatch.duration_ms,
    )


async def run_generation_pipeline(
    text: str,
    settings: Settings | None = None,
    *,
    project_id: str = "",
    job_id: str = "",
    user_id: str = "",
) -> PipelineResult:
    if _env_bool("GENERATION_SECTION_GATE_ENABLED", False):
        return await _run_section_gated_generation_pipeline(
            text,
            settings=settings,
            project_id=project_id,
            job_id=job_id,
            user_id=user_id,
        )

    phase_result = await _run_pipeline_until_formatting(
        text,
        settings=settings,
        project_id=project_id,
    )
    total_duration_ms = (perf_counter() - phase_result.start_time) * 1000
    validation_events = list(phase_result.validation_events)
    validation_events.append("pipeline: formatting boundary reached; humanizer/originality deferred")
    metadata = GenerationMetadata(
        **_build_common_metadata_fields(
            phase_result,
            total_duration_ms=total_duration_ms,
            validation_events=validation_events,
            agent_timings=[
                AgentTiming(
                    agent=phase_result.structuring_agent.agent_name,
                    duration_ms=phase_result.structuring_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.writing_agent.agent_name,
                    duration_ms=phase_result.writing_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.figure_table_agent.agent_name,
                    duration_ms=phase_result.figure_table_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.citation_agent.agent_name,
                    duration_ms=phase_result.citation_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.formatting_agent.agent_name,
                    duration_ms=phase_result.formatting_duration_ms,
                ),
            ],
        )
    )
    remediation_context = _build_remediation_context(phase_result)
    generated_paper = await _run_generation_preflight(
        generated_paper=_build_generated_paper_from_formatting(phase_result.formatting_result),
        phase_result=phase_result,
        remediation_context=remediation_context,
        source_text=text,
        job_id=job_id,
        project_id=project_id,
        user_id=user_id,
    )

    logger.info(
        "Generation pipeline trace %s reached formatting boundary in %.2f ms",
        phase_result.trace_id,
        total_duration_ms,
    )
    return PipelineResult(
        generated_paper=generated_paper,
        metadata=metadata,
        generated_figures=phase_result.pipeline_context.get("generated_figures"),
        generated_tables=phase_result.pipeline_context.get("generated_tables"),
        figure_table_status=phase_result.pipeline_context.get("figure_table_status"),
        figure_table_error=phase_result.pipeline_context.get("figure_table_error"),
        remediation_context=remediation_context,
    )


async def run_pipeline(
    text: str,
    settings: Settings | None = None,
    *,
    project_id: str = "",
) -> PipelineResult:
    phase_result = await _run_pipeline_until_formatting(
        text,
        settings=settings,
        project_id=project_id,
    )
    humanizer_agent = HumanizerAgent(
        phase_result.vertex_client,
        phase_result.registry.get("humanizer_agent"),
    )
    originality_agent = OriginalityAgent(phase_result.registry.get("originality_agent"))
    phase_result.a2a_manager.register(originality_agent)

    humanizer_started = perf_counter()
    humanizer_result = _execute_humanizer_loop(
        humanizer_agent=humanizer_agent,
        paper=phase_result.formatting_result.paper,
        trace_id=phase_result.trace_id,
        pipeline_context=phase_result.pipeline_context,
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
    phase_result.validation_events.append(
        f"{humanizer_agent.agent_name}: completed with action {humanizer_result.graph_action or 'accept'}"
    )

    originality_result, originality_dispatch = await _dispatch_validated_stage(
        a2a_manager=phase_result.a2a_manager,
        sender=humanizer_agent.agent_name,
        recipient=originality_agent.agent_name,
        task="review_originality_and_compliance",
        trace_id=phase_result.trace_id,
        payload={
            "paper": humanizer_result.model_dump(),
            "citation_draft": phase_result.citation_result.citation_draft,
        },
        response_model=OriginalityAgentOutput,
        require_references=True,
        validation_events=phase_result.validation_events,
    )

    if originality_result.error is not None:
        _raise_agent_runtime_error(
            agent_name=originality_agent.agent_name,
            error_payload=originality_result.error,
            default_message="Originality review failed.",
        )

    total_duration_ms = (perf_counter() - phase_result.start_time) * 1000
    originality_report = originality_result.originality_report or {}
    section_reports = originality_report.get("sections") or {}
    flagged_span_count = sum(len((section or {}).get("spans") or []) for section in section_reports.values())
    metadata = GenerationMetadata(
        **_build_common_metadata_fields(
            phase_result,
            total_duration_ms=total_duration_ms,
            validation_events=phase_result.validation_events,
            agent_timings=[
                AgentTiming(
                    agent=phase_result.structuring_agent.agent_name,
                    duration_ms=phase_result.structuring_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.writing_agent.agent_name,
                    duration_ms=phase_result.writing_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.figure_table_agent.agent_name,
                    duration_ms=phase_result.figure_table_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.citation_agent.agent_name,
                    duration_ms=phase_result.citation_duration_ms,
                ),
                AgentTiming(
                    agent=phase_result.formatting_agent.agent_name,
                    duration_ms=phase_result.formatting_duration_ms,
                ),
                AgentTiming(agent=humanizer_agent.agent_name, duration_ms=humanizer_duration_ms),
                AgentTiming(agent=originality_agent.agent_name, duration_ms=originality_dispatch.duration_ms),
            ],
        ),
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
                "trace_id": phase_result.trace_id,
                "graph_action": originality_result.decision_graph_action or "needs_manual_review",
                "originality_report": originality_report,
            },
        )

    generated_paper = originality_result.approved_snapshot
    remediation_context = _build_remediation_context(phase_result)

    logger.info("Pipeline trace %s completed in %.2f ms", phase_result.trace_id, total_duration_ms)
    return PipelineResult(
        generated_paper=generated_paper,
        metadata=metadata,
        generated_figures=phase_result.pipeline_context.get("generated_figures"),
        generated_tables=phase_result.pipeline_context.get("generated_tables"),
        figure_table_status=phase_result.pipeline_context.get("figure_table_status"),
        figure_table_error=phase_result.pipeline_context.get("figure_table_error"),
        remediation_context=remediation_context,
    )
