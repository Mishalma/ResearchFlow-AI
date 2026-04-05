from __future__ import annotations

from fastapi import APIRouter, File, UploadFile, status

from app.core.config import get_settings
from app.models.project import ProjectRecord, UploadResponse, save_project
from app.services.extraction_service import extract_text
from app.services.file_service import delete_file, store_upload_file

router = APIRouter(tags=["upload"])
settings = get_settings()


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...)) -> UploadResponse:
    stored_file = await store_upload_file(
        upload_file=file,
        upload_dir=settings.uploads_dir,
        max_size_bytes=settings.max_upload_size_bytes,
        max_size_mb=settings.max_upload_size_mb,
    )

    try:
        extraction_result = extract_text(stored_file.file_path)
    except Exception:
        delete_file(stored_file.file_path)
        raise

    project = ProjectRecord(
        id=stored_file.project_id,
        file_name=stored_file.file_name,
        file_path=str(stored_file.file_path),
        extracted_text=extraction_result.text,
        file_type=stored_file.file_type,
        file_size=stored_file.file_size,
        extraction_time_ms=extraction_result.extraction_time_ms,
    )
    save_project(project)

    return UploadResponse.from_project(project)
