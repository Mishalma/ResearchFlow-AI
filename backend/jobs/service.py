from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.auth import AuthenticatedRequestUser
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
    load_job_result_report,
    store_extracted_text_artifact,
    store_final_accepted_draft_artifact,
    store_generated_draft_artifact,
    store_job_result_report,
)
from jobs.dispatcher import get_job_dispatcher
from jobs.repository import ACTIVE_JOB_STATUSES, get_job_repository
from models.generation import GenerationServiceRequest
from models.job import (
    CreateJobResponse,
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
from app.services.generation_service import get_generation_service_client
from app.services.project_service import get_project, save_generated_paper
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


def _progress_for_status(status: str) -> JobProgress:
    if status in {"CREATED", "GENERATION_REQUESTED"}:
        return JobProgress(current_step="queued", percent=25)
    if status == "GENERATING":
        return JobProgress(current_step="generation", percent=70)
    if status == "GENERATED":
        return JobProgress(current_step="generation", percent=90)
    if status == "DONE":
        return JobProgress(current_step="complete", percent=100)
    return JobProgress(current_step="failed", percent=100)


def _result_artifacts_from_job(job: JobRecord) -> JobResultArtifacts:
    return JobResultArtifacts(
        raw_upload_uri=job.artifacts.raw_upload.uri if job.artifacts.raw_upload else None,
        extracted_text_uri=job.artifacts.extracted_text.uri if job.artifacts.extracted_text else None,
        draft_v1_uri=job.artifacts.draft_v1.uri if job.artifacts.draft_v1 else None,
        draft_v2_uri=job.artifacts.draft_v2.uri if job.artifacts.draft_v2 else None,
        draft_v3_uri=job.artifacts.draft_v3.uri if job.artifacts.draft_v3 else None,
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
) -> JobResultResponse:
    project = get_project(job.project_id, job.user_id)
    return JobResultResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        status="DONE" if final_disposition != "failed" else "FAILED",
        final_disposition=final_disposition,
        validation_mode=job.validation_mode,
        boundary=boundary,
        editor_url=f"/editor?projectId={job.project_id}" if final_disposition != "failed" else None,
        generated_paper=project.generated_paper,
        metadata=project.generation_metadata,
        artifacts=_result_artifacts_from_job(job),
        error=job.error,
    )


def create_generation_job(
    *,
    project_id: str,
    current_user: AuthenticatedRequestUser,
    idempotency_key: str,
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
        final_accepted_draft = store_final_accepted_draft_artifact(
            job.project_id,
            job.job_id,
            generation_result.generated_paper,
        )

        score_update = WorkflowScores(
            ai_score=None,
            plagiarism_score=None,
            confidence_band="unknown",
            routing_decision="pending",
            deep_validation_used=False,
        )

        job = _save_job(
            job,
            status="GENERATED",
            stage="finalize",
            current_draft_uri=draft_v1.uri,
            artifacts=job.artifacts.model_copy(
                update={
                    "draft_v1": draft_v1,
                    "final_accepted_draft": final_accepted_draft,
                }
            ),
            scores=score_update,
            error=None,
        )

        predicted_final_report_uri = get_object_storage().get_uri(build_final_report_key(job.project_id, job.job_id))
        result = JobResultResponse(
            job_id=job.job_id,
            project_id=job.project_id,
            status="DONE",
            final_disposition="accepted",
            validation_mode=job.validation_mode,
            boundary="formatting_complete",
            editor_url=f"/editor?projectId={job.project_id}",
            generated_paper=updated_project.generated_paper,
            metadata=updated_project.generation_metadata,
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
            current_draft_uri=draft_v1.uri,
        )
    except Exception as exc:
        logger.exception("Workflow generation failed for job %s", job.job_id)
        _save_job(
            job,
            status="FAILED",
            stage="failed",
            error=_job_error("generation", exc),
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
        progress=_progress_for_status(job.status),
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
