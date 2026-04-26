from __future__ import annotations

import logging
import os
import re
from dataclasses import replace

from humanizer.agent import HumanizerRuntimeAgent
from humanizer.config import HumanizerConfig
from humanizer.utils import build_generated_paper, build_section_text_map
from jobs.artifacts import (
    load_generated_draft_artifact,
    load_remediation_context_artifact,
    load_validation_report_artifact,
    store_generated_draft_artifact,
)
from models.fix import FixSectionTarget, FixServiceRequest, FixServiceResponse
from models.validation import ValidationCandidate, ValidationCandidateScoringRequest, ValidationSectionFlag
from validation.runtime import score_validation_candidates
from core.config import Settings, get_settings

logger = logging.getLogger("papereasy.fix.runtime")


def _resolve_humanizer_config(settings: Settings) -> HumanizerConfig:
    config = HumanizerConfig.from_settings(settings)
    use_model_rewriter = config.use_model_rewriter
    enable_perplexity = config.enable_perplexity
    if "HUMANIZER_USE_MODEL_REWRITER" not in os.environ:
        use_model_rewriter = None
    if "HUMANIZER_ENABLE_PERPLEXITY" not in os.environ:
        enable_perplexity = False
    return replace(
        config,
        use_model_rewriter=use_model_rewriter,
        enable_perplexity=enable_perplexity,
    )


def _next_draft_version(current_draft_uri: str) -> str:
    match = re.search(r"draft_v(\d+)\.json$", str(current_draft_uri or ""))
    if not match:
        return "draft_v2"
    next_version = int(match.group(1)) + 1
    if next_version > 5:
        raise ValueError("Fix loop exceeded the supported immutable draft versions.")
    return f"draft_v{next_version}"


def _load_section_targets(request: FixServiceRequest) -> list[FixSectionTarget]:
    if request.targets:
        return list(request.targets)

    payload = load_validation_report_artifact(request.validation_report_uri)
    raw_flags = payload.get("section_flags", [])
    targets: list[FixSectionTarget] = []
    for raw_flag in raw_flags:
        flag = ValidationSectionFlag.model_validate(raw_flag)
        if flag.flag_type != "ai" or flag.risk not in {"medium", "severe"}:
            continue
        targets.append(
            FixSectionTarget(
                section_id=flag.section_id,
                flag_type="ai",
                risk=flag.risk,
                score=min(1.0, float(flag.score)),
                summary=flag.summary,
            )
        )
    return targets


async def _filter_changed_sections_with_validation(
    *,
    request: FixServiceRequest,
    original_sections: dict[str, str],
    updated_sections: dict[str, str],
    changed_sections: list[str],
    settings: Settings,
) -> tuple[list[str], list[str], float | None, float | None]:
    if not changed_sections or not request.artifacts.extracted_text_uri:
        return changed_sections, [], None, None

    try:
        response = await score_validation_candidates(
            ValidationCandidateScoringRequest(
                task_id=f"fix-candidate-score-{request.job_id}-v{request.iteration}",
                job_id=request.job_id,
                project_id=request.project_id,
                user_id=request.user_id,
                idempotency_key=f"{request.idempotency_key}-score",
                extracted_text_uri=request.artifacts.extracted_text_uri,
                candidates=[
                    ValidationCandidate(
                        candidate_id=section_id,
                        section_id=section_id,
                        text=updated_sections.get(section_id, ""),
                        original_text=original_sections.get(section_id, ""),
                    )
                    for section_id in changed_sections
                ],
            ),
            settings=settings,
        )
    except Exception as exc:
        logger.warning("Fix candidate validation scoring failed for job %s: %s", request.job_id, exc)
        for section_id in changed_sections:
            updated_sections[section_id] = original_sections.get(section_id, "")
        return [], ["candidate_scoring_failed"], None, None

    accepted_sections = {result.section_id for result in response.results if result.accepted}
    rejected_reasons: list[str] = []
    best_ai_score: float | None = None
    best_overlap_score: float | None = None
    for result in response.results:
        if result.ai_score is not None:
            best_ai_score = result.ai_score if best_ai_score is None else min(best_ai_score, result.ai_score)
        best_overlap_score = (
            result.overlap_score if best_overlap_score is None else min(best_overlap_score, result.overlap_score)
        )
        if result.accepted:
            continue
        for reason in result.rejection_reasons:
            if reason not in rejected_reasons:
                rejected_reasons.append(reason)
        updated_sections[result.section_id] = original_sections.get(result.section_id, "")

    return (
        [section_id for section_id in changed_sections if section_id in accepted_sections],
        rejected_reasons,
        best_ai_score,
        best_overlap_score,
    )


async def execute_fix_request(
    request: FixServiceRequest,
    *,
    settings: Settings | None = None,
) -> FixServiceResponse:
    resolved_settings = settings or get_settings()
    draft = load_generated_draft_artifact(request.current_draft_uri)
    remediation_context = load_remediation_context_artifact(request.artifacts.remediation_context_uri)
    targets = _load_section_targets(request)

    if not targets:
        fix_summary = {
            "attempted": False,
            "status": "not_needed",
            "iterations": request.iteration,
            "changed_sections": [],
            "rewriter_mode": None,
            "fallback_reason": None,
            "strategy": None,
            "candidate_count": 0,
            "accepted_candidate_count": 0,
            "best_candidate_ai_score": None,
            "best_candidate_overlap_score": None,
            "failure_reasons": [],
            "retry_recommended": False,
        }
        return FixServiceResponse(
            job_id=request.job_id,
            output={
                "mode": request.mode,
                "updated_draft_uri": request.current_draft_uri,
                "draft_artifact": None,
                "changed_sections": [],
                "changed": False,
                "rewriter_mode": None,
                "fix_status": "not_needed",
                "fallback_reason": None,
                "fix_summary": fix_summary,
            },
        )

    section_map = build_section_text_map(draft.paper)
    target_section_ids = {target.section_id for target in targets}
    humanizer_config = _resolve_humanizer_config(resolved_settings)
    runtime = HumanizerRuntimeAgent(
        config=humanizer_config,
        settings=resolved_settings,
    )
    try:
        runtime_result = runtime.run(
            section_map,
            iteration=request.iteration,
            target_sections=target_section_ids,
            remediation_context=remediation_context,
        )
    except TypeError as exc:
        if "remediation_context" not in str(exc):
            raise
        runtime_result = runtime.run(
            section_map,
            iteration=request.iteration,
            target_sections=target_section_ids,
        )
    changed_sections = [
        section_id
        for section_id in target_section_ids
        if runtime_result["updated_sections"].get(section_id, "").strip()
        != section_map.get(section_id, "").strip()
    ]
    scoring_failure_reasons: list[str] = []
    scoring_best_ai_score: float | None = None
    scoring_best_overlap_score: float | None = None
    validation_scoring_applied = bool(changed_sections and request.artifacts.extracted_text_uri)
    if changed_sections:
        (
            changed_sections,
            scoring_failure_reasons,
            scoring_best_ai_score,
            scoring_best_overlap_score,
        ) = await _filter_changed_sections_with_validation(
            request=request,
            original_sections=section_map,
            updated_sections=runtime_result["updated_sections"],
            changed_sections=changed_sections,
            settings=resolved_settings,
        )
    rewriter_mode = runtime_result.get("rewriter_mode")
    failure_reasons = list(runtime_result.get("failure_reasons", []))
    for reason in scoring_failure_reasons:
        if reason not in failure_reasons:
            failure_reasons.append(reason)
    fallback_reason = failure_reasons[0] if failure_reasons else None
    if changed_sections:
        generated_paper = build_generated_paper(
            source_paper=draft.paper,
            section_texts=runtime_result["updated_sections"],
        )
        draft_artifact = store_generated_draft_artifact(
            request.project_id,
            request.job_id,
            version=_next_draft_version(request.current_draft_uri),
            generated_paper=generated_paper,
            owner_service="fix-service",
        )
        updated_draft_uri = draft_artifact.uri
        fix_status = "applied"
        changed = True
        fallback_reason = None
    else:
        draft_artifact = None
        updated_draft_uri = request.current_draft_uri
        fix_status = "no_change"
        changed = False
    retry_limit = min(3, max(1, int(humanizer_config.max_iterations)))
    retry_recommended = (
        not changed
        and bool(runtime_result.get("retry_recommended"))
        and request.iteration < retry_limit
    )
    fix_summary = {
        "attempted": True,
        "status": fix_status,
        "iterations": request.iteration,
        "changed_sections": changed_sections,
        "rewriter_mode": rewriter_mode,
        "fallback_reason": fallback_reason,
        "strategy": runtime_result.get("strategy"),
        "candidate_count": int(runtime_result.get("candidate_count") or 0),
        "accepted_candidate_count": len(changed_sections)
        if validation_scoring_applied
        else int(runtime_result.get("accepted_candidate_count") or 0),
        "best_candidate_ai_score": scoring_best_ai_score
        if scoring_best_ai_score is not None
        else runtime_result.get("best_candidate_ai_score"),
        "best_candidate_overlap_score": scoring_best_overlap_score
        if scoring_best_overlap_score is not None
        else runtime_result.get("best_candidate_overlap_score"),
        "failure_reasons": failure_reasons,
        "retry_recommended": retry_recommended,
    }
    logger.info(
        "Fix request %s completed with status=%s changed_sections=%s mode=%s fallback_reason=%s",
        request.job_id,
        fix_status,
        changed_sections,
        rewriter_mode,
        fallback_reason,
    )
    return FixServiceResponse(
        job_id=request.job_id,
        output={
            "mode": request.mode,
            "updated_draft_uri": updated_draft_uri,
            "draft_artifact": draft_artifact,
            "changed_sections": changed_sections,
            "changed": changed,
            "rewriter_mode": rewriter_mode,
            "fix_status": fix_status,
            "fallback_reason": fallback_reason,
            "fix_summary": fix_summary,
        },
    )
