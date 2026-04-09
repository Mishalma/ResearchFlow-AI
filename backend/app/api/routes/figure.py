from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import Response

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.core.config import get_settings
from app.models.project import FigureSection
from app.schemas.figure_schema import FigureUploadResponse
from app.services.project_service import get_project_figure
from persistence import get_object_storage
from services.figure_service import store_project_figure

router = APIRouter(tags=["figure"])
settings = get_settings()


@router.post("/figure/upload", response_model=FigureUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_figure(
    project_id: str = Form(...),
    caption: str = Form(...),
    section: FigureSection = Form(...),
    file: UploadFile = File(...),
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> FigureUploadResponse:
    figure = await store_project_figure(
        project_id=project_id,
        owner_uid=current_user.user_id,
        upload_file=file,
        caption=caption,
        section=section,
        figures_dir=settings.figures_dir,
        temp_dir=settings.temp_dir,
        object_storage=get_object_storage(),
        max_size_bytes=settings.max_figure_size_bytes,
        max_size_mb=settings.max_figure_size_mb,
    )
    return FigureUploadResponse(project_id=project_id, figure=figure)


@router.get("/figure/{project_id}/{figure_id}")
async def download_figure(
    project_id: str,
    figure_id: str,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> Response:
    figure = get_project_figure(project_id, current_user.user_id, figure_id)
    downloaded = get_object_storage().download_bytes(figure.path)
    return Response(
        content=downloaded.content,
        media_type=downloaded.content_type or figure.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{figure.stored_file_name}"'},
    )
