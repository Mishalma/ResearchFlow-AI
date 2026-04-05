from __future__ import annotations

from fastapi import APIRouter, status

from app.core.exceptions import EmptyGenerationSourceError, ProjectNotFoundError
from app.models.generation import GenerateRequest, GenerateResponse
from app.models.project import get_project, save_generated_paper
from orchestration.pipeline import run_pipeline

router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_200_OK)
async def generate_paper(request: GenerateRequest) -> GenerateResponse:
    project = get_project(request.project_id)
    if project is None:
        raise ProjectNotFoundError(request.project_id)

    if not project.extracted_text.strip():
        raise EmptyGenerationSourceError(request.project_id)

    pipeline_result = await run_pipeline(project.extracted_text)
    updated_project = save_generated_paper(
        project_id=project.id,
        generated_paper=pipeline_result.generated_paper,
        generation_metadata=pipeline_result.metadata,
    )
    if updated_project is None:
        raise ProjectNotFoundError(request.project_id)

    return GenerateResponse.from_generation(
        project_id=updated_project.id,
        generated_paper=pipeline_result.generated_paper,
        metadata=pipeline_result.metadata,
    )
