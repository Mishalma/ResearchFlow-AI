from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, status

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.models.job import CreateJobRequest, CreateJobResponse, JobResultResponse, JobStatusResponse
from jobs.service import (
    build_create_job_response,
    create_generation_job,
    dispatch_job_after_response,
    get_job_result,
    get_job_status,
)

router = APIRouter(tags=["jobs"])


@router.post("/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreateJobResponse:
    job, created = create_generation_job(
        project_id=request.project_id,
        current_user=current_user,
        idempotency_key=(idempotency_key or "").strip() or f"phase1-job-{request.project_id}",
    )
    if created:
        background_tasks.add_task(dispatch_job_after_response, job.job_id)
    return build_create_job_response(job)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> JobStatusResponse:
    return get_job_status(job_id, current_user.user_id)


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_job_result_payload(
    job_id: str,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> JobResultResponse:
    return get_job_result(job_id, current_user.user_id)
