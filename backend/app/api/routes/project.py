from __future__ import annotations

from fastapi import APIRouter

from app.schemas.project_schema import ProjectResponse
from app.services.project_service import get_project_response

router = APIRouter(tags=["project"])


@router.get("/project/{project_id}", response_model=ProjectResponse)
async def get_project_by_id(project_id: str) -> ProjectResponse:
    return get_project_response(project_id)
