from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.auth import AuthenticatedRequestUser
from core.config import get_settings
from core.exceptions import (
    AppError,
    EmptyGenerationSourceError,
    WorkflowJobActiveError,
    WorkflowJobConflictError,
    WorkflowJobNotFoundError,
    WorkflowJobResultNotReadyError,
)
from jobs.artifacts import (
    build_final_report_key,
    load_generated_draft_artifact,
    load_job_result_report,
    store_extracted_text_artifact,
    store_final_accepted_draft_artifact,
    store_generated_draft_artifact,
    store_job_result_report,
    store_remediation_context_artifact,
)
from jobs.dispatcher import get_job_dispatcher
from jobs.repository import ACTIVE_JOB_STATUSES, get_job_repository
from models.generation import GenerationServiceRequest
from models.fix import FixSectionTarget, FixServiceRequest
from models.job import (
    CreateJobResponse,
    FixSummary,
    GenerationTaskRequest,
    JobProgress,
    JobRecord,
    JobResultArtifacts,
    JobResultResponse,
    JobStatusResponse,
    WorkflowArtifacts,
    WorkflowBoundary,
    WorkflowErrorPayload,
    WorkflowFinalDisposition,
    WorkflowScores,
)
from models.validation import ValidationServiceOutput
from app.services.fix_service import get_fix_service_client
from app.services.generation_service import get_generation_service_client
from app.services.validation_service import get_validation_service_client
from app.services.project_service import get_project, save_generated_paper
from models.validation import ValidationServiceRequest
from persistence import get_object_storage

logger = logging.getLogger("papereasy.backend.jobs.service")


def _timestamp() -> datetime:
    return datetime.now(UTC)


def _build_poll_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}"


def _build_result_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}/result"


def _job_error(stage: str, error: Exception, *, retryable: bool = False, attempt: int | None = None) -> WorkflowErrorPayload:
    if isinstance(error, AppError):
        message = error.message
    else:
        message = str(error) or "Unexpected workflow error."

    return WorkflowErrorPayload(
        stage=stage,
        code=error.__class__.__name__,
        message=message,
        retryable=retryable,
        attempt=attempt,
    )


def _progress_for_job(job: JobRecord) -> JobProgress:
    status = job.status
    if status in {"CREATED", "GENERATION_REQUESTED"}:
        return JobProgress(current_step="queued", percent=20)
    if status == "GENERATING":
        return JobProgress(current_step="generation", percent=55)
    if status in {"GENERATED", "VALIDATION_REQUESTED", "VALIDATING"}:
        return JobProgress(current_step="validation", percent=80 if status != "VALIDATING" else 88)
    if status in {"FIX_REQUESTED", "FIXING"}:
        return JobProgress(current_step="fixing", percent=92)
    if status == "FINALIZING":
        return JobProgress(current_step="finalizing", percent=96)
    if status == "DONE":
        return JobProgress(current_step="complete", percent=100)
    return JobProgress(current_step="failed", percent=100)


def _result_artifacts_from_job(job: JobRecord) -> JobResultArtifacts:
    return JobResultArtifacts(
        raw_upload_uri=job.artifacts.raw_upload.uri if job.artifacts.raw_upload else None,
        extracted_text_uri=job.artifacts.extracted_text.uri if job.artifacts.extracted_text else None,
        remediation_context_uri=(
            job.artifacts.remediation_context.uri if job.artifacts.remediation_context else None
        ),
        draft_v1_uri=job.artifacts.draft_v1.uri if job.artifacts.draft_v1 else None,
        draft_v2_uri=job.artifacts.draft_v2.uri if job.artifacts.draft_v2 else None,
        draft_v3_uri=job.artifacts.draft_v3.uri if job.artifacts.draft_v3 else None,
        draft_v4_uri=job.artifacts.draft_v4.uri if job.artifacts.draft_v4 else None,
        draft_v5_uri=job.artifacts.draft_v5.uri if job.artifacts.draft_v5 else None,
        final_report_uri=job.artifacts.final_report.uri if job.artifacts.final_report else None,
        final_accepted_draft_uri=(
            job.artifacts.final_accepted_draft.uri if job.artifacts.final_accepted_draft else None
        ),
    )


def _get_job_or_raise(job_id: str) -> JobRecord:
    job = get_job_repository().get(job_id)
    if job is None:
        raise WorkflowJobNotFoundError(job_id)
    return job


def _get_user_job_or_raise(job_id: str, user_id: str) -> JobRecord:
    job = _get_job_or_raise(job_id)
    if job.user_id != user_id:
        raise WorkflowJobNotFoundError(job_id)
    return job


def _save_job(job: JobRecord, **updates: Any) -> JobRecord:
    payload = updates.copy()
    timestamps = job.timestamps.model_copy(update={"updated_at": _timestamp()})
    payload["timestamps"] = payload.get("timestamps", timestamps)
    updated = job.model_copy(update=payload)
    return get_job_repository().save(updated)


def _build_job_result(
    job: JobRecord,
    *,
    final_disposition: WorkflowFinalDisposition,
    boundary: WorkflowBoundary | None,
    fix_summary: FixSummary | None = None,
) -> JobResultResponse:
    project = get_project(job.project_id, job.user_id)
    return JobResultResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        status="DONE" if final_disposition != "failed" else "FAILED",
        final_disposition=final_disposition,
        validation_mode=job.validation_mode,
        boundary=boundary,
        editor_url=(
            f"/editor?projectId={job.project_id}"
            if final_disposition in {"accepted", "accepted_after_fix"}
            else None
        ),
        generated_paper=project.generated_paper,
        metadata=project.generation_metadata,
        report=None,
        fix_summary=fix_summary,
        artifacts=_result_artifacts_from_job(job),
        error=job.error,
    )


def _final_disposition_from_routing(routing_decision: str) -> WorkflowFinalDisposition:
    if routing_decision == "accepted":
        return "accepted"
    if routing_decision == "flagged":
        return "flagged"
    return "failed"


def _build_fix_targets(validation_output: ValidationServiceOutput) -> list[FixSectionTarget]:
    targets: list[FixSectionTarget] = []
    for flag in validation_output.section_flags:
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


def _fix_iteration_available(job: JobRecord) -> bool:
    return job.enable_fix_loop and job.iteration < job.max_iterations


def create_generation_job(
    *,
    project_id: str,
    current_user: AuthenticatedRequestUser,
    idempotency_key: str,
    enable_fix_loop: bool = True,
    max_iterations: int = 3,
) -> tuple[JobRecord, bool]:
    normalized_key = idempotency_key.strip()
    if len(normalized_key) < 8:
        raise WorkflowJobConflictError("A valid Idempotency-Key header is required.")

    repository = get_job_repository()
    existing = repository.find_by_idempotency(
        user_id=current_user.user_id,
        project_id=project_id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing, False

    active_job = repository.find_active_by_user(current_user.user_id)
    if active_job is not None and active_job.status in ACTIVE_JOB_STATUSES:
        raise WorkflowJobActiveError()

    project = get_project(project_id, current_user.user_id)
    if not project.extracted_text.strip():
        raise EmptyGenerationSourceError(project_id)

    job_id = str(uuid4())
    extracted_text_artifact = store_extracted_text_artifact(project_id, job_id, project.extracted_text)
    job = JobRecord(
        job_id=job_id,
        project_id=project_id,
        user_id=current_user.user_id,
        idempotency_key=normalized_key,
        enable_fix_loop=enable_fix_loop,
        max_iterations=max(1, min(3, int(max_iterations))),
        artifacts=WorkflowArtifacts(
            raw_upload=None,
            extracted_text=extracted_text_artifact,
        ),
    )
    repository.save(job)
    return job, True


def build_create_job_response(job: JobRecord) -> CreateJobResponse:
    return CreateJobResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        poll_url=_build_poll_url(job.job_id),
        result_url=_build_result_url(job.job_id),
    )


async def dispatch_job_after_response(job_id: str) -> None:
    repository = get_job_repository()
    job = repository.get(job_id)
    if job is None:
        logger.warning("Skipping dispatch for missing workflow job %s", job_id)
        return
    if job.status != "CREATED":
        logger.info("Skipping dispatch for workflow job %s in state %s", job_id, job.status)
        return

    dispatcher = get_job_dispatcher(runner=run_generation_task)
    job = _save_job(
        job,
        status="GENERATION_REQUESTED",
        stage="job",
        error=None,
    )
    try:
        active_task = await dispatcher.dispatch_generation(job)
    except Exception as exc:
        logger.exception("Unable to dispatch workflow job %s", job_id)
        _save_job(
            job,
            status="FAILED",
            stage="failed",
            error=_job_error("job", exc),
            timestamps=job.timestamps.model_copy(update={"updated_at": _timestamp(), "completed_at": _timestamp()}),
        )
        return

    _save_job(
        job,
        active_task=active_task,
    )


async def run_generation_task(task_request: GenerationTaskRequest) -> None:
    repository = get_job_repository()
    job = repository.get(task_request.job_id)
    if job is None:
        logger.warning("Received generation task for missing job %s", task_request.job_id)
        return
    if job.status == "DONE":
        logger.info("Skipping completed workflow job %s", job.job_id)
        return
    if job.status == "FAILED":
        logger.info("Skipping failed workflow job %s", job.job_id)
        return
    if job.status not in {"GENERATION_REQUESTED", "GENERATING"}:
        logger.info("Skipping workflow job %s in state %s", job.job_id, job.status)
        return

    job = _save_job(
        job,
        status="GENERATING",
        stage="generation",
        active_task=job.active_task,
        timestamps=job.timestamps.model_copy(
            update={
                "updated_at": _timestamp(),
                "started_at": job.timestamps.started_at or _timestamp(),
            }
        ),
    )

    try:
        project = get_project(job.project_id, job.user_id)
        generation_client = get_generation_service_client()
        generation_result = await generation_client.run_generation(
            GenerationServiceRequest(
                job_id=job.job_id,
                project_id=project.id,
                source_text=project.extracted_text,
                user_id=job.user_id,
                idempotency_key=job.idempotency_key,
            )
        )
        updated_project = save_generated_paper(
            project_id=project.id,
            owner_uid=job.user_id,
            generated_paper=generation_result.generated_paper,
            generation_metadata=generation_result.metadata,
            generated_figures=(
                [item.model_dump(mode="python") for item in generation_result.generated_figures]
                if generation_result.generated_figures is not None
                else None
            ),
            generated_tables=(
                [item.model_dump(mode="python") for item in generation_result.generated_tables]
                if generation_result.generated_tables is not None
                else None
            ),
            figure_table_status=generation_result.figure_table_status,
            figure_table_error=generation_result.figure_table_error,
        )

        draft_v1 = store_generated_draft_artifact(
            job.project_id,
            job.job_id,
            version="draft_v1",
            generated_paper=generation_result.generated_paper,
        )
        remediation_context_artifact = (
            store_remediation_context_artifact(
                job.project_id,
                job.job_id,
                generation_result.remediation_context,
                revision="v1",
                owner_service="generation-service",
            )
            if generation_result.remediation_context
            else None
        )

        score_update = WorkflowScores(
            ai_score=None,
            plagiarism_score=None,
            confidence_band="unknown",
            routing_decision="pending",
        )

        job = _save_job(
            job,
            status="GENERATED",
            stage="generation",
            current_draft_uri=draft_v1.uri,
            artifacts=job.artifacts.model_copy(
                update={
                    "draft_v1": draft_v1,
                    "remediation_context": remediation_context_artifact,
                }
            ),
            scores=score_update,
            error=None,
        )

        resolved_settings = get_settings()
        validation_client = get_validation_service_client()
        fix_client = get_fix_service_client()
        current_draft_uri = draft_v1.uri
        previous_validation_report_uri: str | None = None
        changed_section_ids: list[str] = []
        latest_validation_output: ValidationServiceOutput | None = None
        fix_summary = FixSummary(
            attempted=False,
            status="not_needed",
            iterations=0,
            changed_sections=[],
            rewriter_mode=None,
        )
        final_disposition: WorkflowFinalDisposition = "flagged"

        async def run_final_report_validation() -> ValidationServiceOutput:
            nonlocal previous_validation_report_uri
            job_for_final_report = _save_job(
                job,
                status="VALIDATION_REQUESTED",
                stage="validation",
                validation_mode="final_report",
                error=None,
            )
            job_for_final_report = _save_job(
                job_for_final_report,
                status="VALIDATING",
                stage="validation",
                validation_mode="final_report",
            )
            validation_result = await validation_client.run_validation(
                ValidationServiceRequest(
                    task_id=f"validation-final-{job.job_id}-v{job.iteration + 1}",
                    job_id=job.job_id,
                    project_id=job.project_id,
                    user_id=job.user_id,
                    idempotency_key=job.idempotency_key,
                    expected_status="VALIDATING",
                    current_draft_uri=current_draft_uri,
                    artifacts={
                        "extracted_text_uri": job.artifacts.extracted_text.uri if job.artifacts.extracted_text else None,
                        "previous_validation_report_uri": previous_validation_report_uri,
                    },
                    config={
                        "mode": "final_report",
                        "changed_sections_only": False,
                        "changed_section_ids": [],
                    },
                )
            )
            previous_validation_report_uri = validation_result.output.validation_report_uri
            return validation_result.output

        while True:
            job = _save_job(
                job,
                status="VALIDATION_REQUESTED",
                stage="validation",
                validation_mode="ai_check",
                error=None,
            )
            job = _save_job(
                job,
                status="VALIDATING",
                stage="validation",
                validation_mode="ai_check",
            )

            validation_result = await validation_client.run_validation(
                ValidationServiceRequest(
                    task_id=f"validation-{job.job_id}-v{job.iteration + 1}",
                    job_id=job.job_id,
                    project_id=job.project_id,
                    user_id=job.user_id,
                    idempotency_key=job.idempotency_key,
                    expected_status="VALIDATING",
                    current_draft_uri=current_draft_uri,
                    artifacts={
                        "extracted_text_uri": job.artifacts.extracted_text.uri if job.artifacts.extracted_text else None,
                        "previous_validation_report_uri": previous_validation_report_uri,
                    },
                    config={
                        "mode": "ai_check",
                        "changed_sections_only": bool(previous_validation_report_uri and changed_section_ids),
                        "changed_section_ids": changed_section_ids,
                    },
                )
            )
            latest_validation_output = validation_result.output
            previous_validation_report_uri = latest_validation_output.validation_report_uri
            changed_section_ids = []

            routing_decision = latest_validation_output.routing_decision
            if routing_decision == "accepted":
                latest_validation_output = await run_final_report_validation()
                final_disposition = (
                    "accepted_after_fix"
                    if latest_validation_output.routing_decision == "accepted" and fix_summary.attempted
                    else "accepted"
                    if latest_validation_output.routing_decision == "accepted"
                    else "flagged"
                )
                current_generated_paper = (
                    load_generated_draft_artifact(current_draft_uri)
                    if fix_summary.attempted or current_draft_uri != draft_v1.uri
                    else generation_result.generated_paper
                )
                updated_project = save_generated_paper(
                    project_id=project.id,
                    owner_uid=job.user_id,
                    generated_paper=current_generated_paper,
                    generation_metadata=generation_result.metadata,
                    generated_figures=(
                        [item.model_dump(mode="python") for item in generation_result.generated_figures]
                        if generation_result.generated_figures is not None
                        else None
                    ),
                    generated_tables=(
                        [item.model_dump(mode="python") for item in generation_result.generated_tables]
                        if generation_result.generated_tables is not None
                        else None
                    ),
                    figure_table_status=generation_result.figure_table_status,
                    figure_table_error=generation_result.figure_table_error,
                )
                break

            fix_targets = _build_fix_targets(latest_validation_output)
            if not fix_targets:
                latest_validation_output = await run_final_report_validation()
                final_disposition = "flagged"
                break

            if not _fix_iteration_available(job):
                latest_validation_output = await run_final_report_validation()
                final_disposition = "flagged"
                break

            next_iteration = job.iteration + 1

            job = _save_job(
                job,
                status="FIX_REQUESTED",
                stage="fix",
                iteration=next_iteration,
                error=None,
            )
            job = _save_job(
                job,
                status="FIXING",
                stage="fix",
            )

            try:
                fix_result = await fix_client.run_fix(
                    FixServiceRequest(
                        task_id=f"fix-{job.job_id}-v{next_iteration}",
                        job_id=job.job_id,
                        project_id=job.project_id,
                        user_id=job.user_id,
                        attempt=next_iteration,
                        idempotency_key=job.idempotency_key,
                        current_draft_uri=current_draft_uri,
                        validation_report_uri=previous_validation_report_uri,
                        iteration=next_iteration,
                        mode="ai_style",
                        targets=fix_targets,
                        artifacts={
                            "remediation_context_uri": job.artifacts.remediation_context.uri
                            if job.artifacts.remediation_context
                            else None,
                            "extracted_text_uri": job.artifacts.extracted_text.uri
                            if job.artifacts.extracted_text
                            else None,
                        },
                    )
                )
            except Exception:
                logger.exception("Fix service failed for job %s", job.job_id)
                fix_summary = FixSummary(
                    attempted=True,
                    status="failed",
                    iterations=next_iteration,
                    changed_sections=[],
                    rewriter_mode=None,
                )
                latest_validation_output = await run_final_report_validation()
                final_disposition = "flagged"
                break

            fix_summary = fix_result.output.fix_summary
            draft_artifact = fix_result.output.draft_artifact
            if (
                fix_result.output.fix_status != "applied"
                or draft_artifact is None
                or not fix_result.output.changed_sections
            ):
                if (
                    fix_result.output.fix_status == "no_change"
                    and fix_summary.retry_recommended
                    and _fix_iteration_available(job)
                ):
                    changed_section_ids = []
                    continue
                latest_validation_output = await run_final_report_validation()
                final_disposition = "flagged"
                break

            current_draft_uri = fix_result.output.updated_draft_uri
            changed_section_ids = list(fix_result.output.changed_sections)
            artifact_updates: dict[str, object] = {}
            if draft_artifact.version in {"draft_v2", "draft_v3", "draft_v4", "draft_v5"}:
                artifact_updates[draft_artifact.version] = draft_artifact
            job = _save_job(
                job,
                current_draft_uri=current_draft_uri,
                artifacts=job.artifacts.model_copy(update=artifact_updates),
                error=None,
            )

        final_accepted_draft = None
        if final_disposition in {"accepted", "accepted_after_fix"}:
            accepted_paper = (
                updated_project.generated_paper
                if final_disposition == "accepted_after_fix"
                else generation_result.generated_paper
            )
            final_accepted_draft = store_final_accepted_draft_artifact(
                job.project_id,
                job.job_id,
                accepted_paper,
            )

        job = _save_job(
            job,
            status="FINALIZING",
            stage="finalize",
            scores=WorkflowScores(
                ai_score=latest_validation_output.ai_score if latest_validation_output else None,
                plagiarism_score=latest_validation_output.plagiarism_score if latest_validation_output else None,
                confidence_band=latest_validation_output.confidence_band if latest_validation_output else "unknown",
                routing_decision=latest_validation_output.routing_decision if latest_validation_output else "pending",
            ),
            artifacts=job.artifacts.model_copy(
                update=(
                    {"final_accepted_draft": final_accepted_draft}
                    if final_accepted_draft is not None
                    else {}
                )
            ),
            error=None,
        )

        predicted_final_report_uri = get_object_storage().get_uri(build_final_report_key(job.project_id, job.job_id))
        result = JobResultResponse(
            job_id=job.job_id,
            project_id=job.project_id,
            status="DONE",
            final_disposition=final_disposition,
            validation_mode=job.validation_mode,
            boundary="formatting_complete",
            editor_url=(
                f"/editor?projectId={job.project_id}"
                if final_disposition in {"accepted", "accepted_after_fix"}
                else None
            ),
            generated_paper=updated_project.generated_paper,
            metadata=updated_project.generation_metadata,
            report=latest_validation_output.report if latest_validation_output else None,
            fix_summary=fix_summary if fix_summary.attempted else None,
            artifacts=_result_artifacts_from_job(job).model_copy(
                update={"final_report_uri": predicted_final_report_uri}
            ),
        )
        final_report = store_job_result_report(job.project_id, job.job_id, result)
        completed_job = _save_job(
            job,
            status="DONE",
            stage="done",
            artifacts=job.artifacts.model_copy(update={"final_report": final_report}),
            timestamps=job.timestamps.model_copy(
                update={"updated_at": _timestamp(), "completed_at": _timestamp()}
            ),
        )
        _save_job(
            completed_job,
            current_draft_uri=current_draft_uri,
        )
    except Exception as exc:
        logger.exception("Workflow generation failed for job %s", job.job_id)
        failed_stage = job.stage if job.stage in {"validation", "finalize"} else "generation"
        _save_job(
            job,
            status="FAILED",
            stage="failed",
            error=_job_error(failed_stage, exc),
            timestamps=job.timestamps.model_copy(
                update={"updated_at": _timestamp(), "completed_at": _timestamp()}
            ),
        )


def get_job_status(job_id: str, user_id: str) -> JobStatusResponse:
    job = _get_user_job_or_raise(job_id, user_id)
    return JobStatusResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        status=job.status,
        stage=job.stage,
        validation_mode=job.validation_mode,
        iteration=job.iteration,
        progress=_progress_for_job(job),
        current_draft_uri=job.current_draft_uri,
        scores=job.scores,
        error=job.error,
    )


def get_job_result(job_id: str, user_id: str) -> JobResultResponse:
    job = _get_user_job_or_raise(job_id, user_id)
    if job.status not in {"DONE", "FAILED"}:
        raise WorkflowJobResultNotReadyError(job.job_id)

    if job.status == "DONE":
        if job.artifacts.final_report is not None:
            return load_job_result_report(job.project_id, job.job_id)
        return _build_job_result(job, final_disposition="accepted", boundary="formatting_complete")

    return JobResultResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        status="FAILED",
        final_disposition="failed",
        validation_mode=job.validation_mode,
        boundary=None,
        editor_url=None,
        generated_paper=None,
        metadata=None,
        artifacts=_result_artifacts_from_job(job),
        error=job.error,
    )
