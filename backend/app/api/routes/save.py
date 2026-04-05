from __future__ import annotations

from fastapi import APIRouter, status

from app.core.exceptions import ProjectSectionsUnavailableError
from app.schemas.project_schema import SaveRequest, SaveResponse
from app.services.project_service import save_project

router = APIRouter(tags=["project"])


@router.post("/save", response_model=SaveResponse, status_code=status.HTTP_200_OK)
async def save_project_sections(request: SaveRequest) -> SaveResponse:
    project = save_project(request.project_id, request.sections)
    sections = project.edited_sections or project.generated_sections
    if sections is None or project.updated_at is None:
        raise ProjectSectionsUnavailableError(request.project_id)

    return SaveResponse(
        project_id=project.id,
        sections=sections,
        updated_at=project.updated_at,
    )
