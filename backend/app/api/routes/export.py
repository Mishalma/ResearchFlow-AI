from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.schemas.export_schema import ExportRequest
from app.services.project_service import get_project_export
from persistence import get_object_storage
from services.export_service import export_project_docx, export_project_latex, export_project_pdf

router = APIRouter(tags=["export"])


def _download_response(*, content: bytes, media_type: str, file_name: str) -> StreamingResponse:
    stream = BytesIO(content)
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def _export_response(exported_file):
    response = _download_response(
        content=exported_file.content,
        media_type=exported_file.media_type,
        file_name=exported_file.artifact.file_name,
    )
    response.headers["X-Export-Id"] = exported_file.artifact.id
    response.headers["X-Export-Format"] = exported_file.artifact.format
    response.headers["X-Export-Download-Url"] = exported_file.artifact.download_url
    return response


@router.post("/export/pdf")
async def export_pdf(
    request: ExportRequest,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
):
    return _export_response(export_project_pdf(request.project_id, current_user.user_id))


@router.post("/export/docx")
async def export_docx(
    request: ExportRequest,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
):
    return _export_response(export_project_docx(request.project_id, current_user.user_id))


@router.post("/export/latex")
async def export_latex(
    request: ExportRequest,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
):
    return _export_response(export_project_latex(request.project_id, current_user.user_id))


@router.get("/export/{project_id}/{export_id}")
async def download_export(
    project_id: str,
    export_id: str,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
):
    artifact = get_project_export(project_id, current_user.user_id, export_id)
    downloaded = get_object_storage().download_bytes(artifact.path)
    return _download_response(
        content=downloaded.content,
        media_type=downloaded.content_type or "application/octet-stream",
        file_name=artifact.file_name,
    )
