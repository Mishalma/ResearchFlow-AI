from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.schemas.project_schema import ProjectResponse, ProjectSummaryResponse
from app.services.project_service import get_project_response, list_project_responses

router = APIRouter(tags=["project"])


@router.get("/projects", response_model=list[ProjectSummaryResponse])
async def get_projects(
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> list[ProjectSummaryResponse]:
    return list_project_responses(current_user.user_id)


@router.get("/project/{project_id}", response_model=ProjectResponse)
async def get_project_by_id(
    project_id: str,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> ProjectResponse:
    return get_project_response(project_id, current_user.user_id)
