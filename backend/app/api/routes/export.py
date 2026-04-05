from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.schemas.export_schema import ExportRequest
from services.export_service import (
    export_project_docx,
    export_project_latex,
    export_project_pdf,
)

router = APIRouter(tags=["export"])


def _file_response(exported_file):
    response = FileResponse(
        path=exported_file.file_path,
        media_type=exported_file.media_type,
        filename=exported_file.artifact.file_name,
    )
    response.headers["X-Export-Id"] = exported_file.artifact.id
    response.headers["X-Export-Format"] = exported_file.artifact.format
    response.headers["X-Export-Download-Url"] = exported_file.artifact.download_url
    return response


@router.post("/export/pdf")
async def export_pdf(request: ExportRequest):
    return _file_response(export_project_pdf(request.project_id))


@router.post("/export/docx")
async def export_docx(request: ExportRequest):
    return _file_response(export_project_docx(request.project_id))


@router.post("/export/latex")
async def export_latex(request: ExportRequest):
    return _file_response(export_project_latex(request.project_id))
