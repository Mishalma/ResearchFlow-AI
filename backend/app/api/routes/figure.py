from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile, status

from app.core.config import get_settings
from app.models.project import FigureSection
from app.schemas.figure_schema import FigureUploadResponse
from services.figure_service import store_project_figure

router = APIRouter(tags=["figure"])
settings = get_settings()


@router.post("/figure/upload", response_model=FigureUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_figure(
    project_id: str = Form(...),
    caption: str = Form(...),
    section: FigureSection = Form(...),
    file: UploadFile = File(...),
) -> FigureUploadResponse:
    figure = await store_project_figure(
        project_id=project_id,
        upload_file=file,
        caption=caption,
        section=section,
        figures_dir=settings.figures_dir,
        max_size_bytes=settings.max_figure_size_bytes,
        max_size_mb=settings.max_figure_size_mb,
    )
    return FigureUploadResponse(project_id=project_id, figure=figure)
