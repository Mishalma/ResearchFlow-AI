from __future__ import annotations

from fastapi import APIRouter, status

from app.models.job import GenerationTaskRequest
from jobs.service import run_generation_task

router = APIRouter(tags=["internal-jobs"])


@router.post("/internal/jobs/run", status_code=status.HTTP_202_ACCEPTED)
async def run_job_task(request: GenerationTaskRequest) -> dict[str, str]:
    await run_generation_task(request)
    return {"status": "accepted"}
