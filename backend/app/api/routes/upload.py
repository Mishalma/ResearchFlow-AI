from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.core.config import get_settings
from app.models.project import ProjectRecord, UploadResponse
from app.services.extraction_service import extract_text
from app.services.file_service import delete_file, store_upload_file
from app.services.project_service import persist_project
from persistence import get_object_storage

router = APIRouter(tags=["upload"])
settings = get_settings()


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> UploadResponse:
    object_storage = get_object_storage()
    stored_file = await store_upload_file(
        upload_file=file,
        upload_dir=settings.uploads_dir,
        temp_dir=settings.temp_dir,
        object_storage=object_storage,
        max_size_bytes=settings.max_upload_size_bytes,
        max_size_mb=settings.max_upload_size_mb,
    )

    try:
        extraction_result = extract_text(stored_file.local_path)
        project = ProjectRecord(
            id=stored_file.project_id,
            file_name=stored_file.file_name,
            file_path=stored_file.storage_key,
            extracted_text=extraction_result.text,
            file_type=stored_file.file_type,
            file_size=stored_file.file_size,
            extraction_time_ms=extraction_result.extraction_time_ms,
            title=Path(stored_file.file_name).stem or "Research Paper",
            owner_uid=current_user.user_id,
            owner_email=current_user.email,
        )
        saved_project = persist_project(project)
        return UploadResponse.from_project(saved_project)
    except Exception:
        object_storage.delete(stored_file.storage_key)
        raise
    finally:
        delete_file(stored_file.local_path)
