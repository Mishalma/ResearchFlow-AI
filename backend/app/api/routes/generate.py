from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, status

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.core.exceptions import EmptyGenerationSourceError
from app.models.generation import GenerateRequest, GenerateResponse
from app.services.project_service import get_project, save_generated_paper
from orchestration.pipeline import run_pipeline

router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_200_OK)
async def generate_paper(
    request: GenerateRequest,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> GenerateResponse:
    project = get_project(request.project_id, current_user.user_id)
    if not project.extracted_text.strip():
        raise EmptyGenerationSourceError(request.project_id)

    pipeline_result = await run_pipeline(project.extracted_text)
    updated_project = save_generated_paper(
        project_id=project.id,
        owner_uid=current_user.user_id,
        generated_paper=pipeline_result.generated_paper,
        generation_metadata=pipeline_result.metadata,
    )

    return GenerateResponse.from_generation(
        project_id=updated_project.id,
        generated_paper=pipeline_result.generated_paper,
        metadata=pipeline_result.metadata,
    )
