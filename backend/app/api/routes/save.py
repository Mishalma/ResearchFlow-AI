from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.schemas.project_schema import ProjectResponse, SaveProjectRequest, SaveProjectResponse
from app.services.project_service import save_project_content

router = APIRouter(tags=["project"])


@router.post("/save", response_model=SaveProjectResponse, status_code=status.HTTP_200_OK)
async def save_project(
    request: SaveProjectRequest,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> SaveProjectResponse:
    project = save_project_content(
        owner_uid=current_user.user_id,
        owner_email=current_user.email,
        project_id=request.project_id,
        title=request.title,
        authors=request.authors,
        keywords=request.keywords,
        content=request.content,
        paper=request.paper,
    )
    return SaveProjectResponse(project=ProjectResponse.from_project(project))
