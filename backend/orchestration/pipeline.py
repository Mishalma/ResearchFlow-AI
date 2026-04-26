from __future__ import annotations

from dataclasses import dataclass
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
from models.validation import ValidationCandidate, ValidationCandidateScoringRequest
from orchestration.a2a_manager import A2AManager, InProcessTransport

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
