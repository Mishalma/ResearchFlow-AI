from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import UploadFile

from app.models.project import FigureRecord, FigureSection
from app.services.file_service import delete_file
from app.services.project_service import add_figure, get_project
from core.exceptions import (
    EmptyFileError,
    FigureStorageError,
    FileTooLargeError,
    InvalidUploadError,
    PersistenceError,
    UnsupportedImageTypeError,
)
from persistence.base import ObjectStorage

logger = logging.getLogger("papereasy.backend.figure")

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
READ_CHUNK_SIZE = 1024 * 1024


def ensure_figure_dir(figures_dir: Path) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)


def _normalize_image_filename(file_name: str | None) -> tuple[str, str]:
    normalized_file_name = Path(file_name or "").name
    if not normalized_file_name:
        raise InvalidUploadError()

    extension = Path(normalized_file_name).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise UnsupportedImageTypeError()

    return normalized_file_name, extension


async def store_project_figure(
    project_id: str,
    owner_uid: str,
    upload_file: UploadFile,
    caption: str,
    section: FigureSection,
    figures_dir: Path,
    temp_dir: Path,
    object_storage: ObjectStorage,
    max_size_bytes: int,
    max_size_mb: int,
) -> FigureRecord:
    get_project(project_id, owner_uid)
    original_file_name, extension = _normalize_image_filename(upload_file.filename)
    normalized_caption = caption.strip()
    if not normalized_caption:
        raise InvalidUploadError("Figure caption is required.")

    ensure_figure_dir(figures_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    figure_id = str(uuid4())
    stored_file_name = f"{figure_id}{extension}"
    total_bytes = 0
    temp_path = Path(
        NamedTemporaryFile(
            delete=False,
            dir=temp_dir,
            prefix=f"figure-{figure_id}-",
            suffix=extension,
        ).name
    )

    try:
        with temp_path.open("wb") as file_buffer:
            while True:
                chunk = await upload_file.read(READ_CHUNK_SIZE)
                if not chunk:
                    break

                total_bytes += len(chunk)
                if total_bytes > max_size_bytes:
                    raise FileTooLargeError(max_size_mb)

                file_buffer.write(chunk)
    except FileTooLargeError:
        delete_file(temp_path)
        raise
    except OSError as exc:
        delete_file(temp_path)
        logger.exception("Unable to stage figure %s", original_file_name)
        raise FigureStorageError() from exc
    finally:
        await upload_file.close()

    if total_bytes == 0:
        delete_file(temp_path)
        raise EmptyFileError()

    storage_key = f"static/figures/{project_id}/{stored_file_name}"
    try:
        object_storage.upload_file(
            storage_key,
            temp_path,
            content_type=upload_file.content_type or "application/octet-stream",
        )
    except PersistenceError as exc:
        delete_file(temp_path)
        raise FigureStorageError(
            "Unable to store the uploaded figure because object storage is unavailable."
        ) from exc
    except Exception:
        delete_file(temp_path)
        raise
    finally:
        delete_file(temp_path)

    figure = FigureRecord(
        id=figure_id,
        original_file_name=original_file_name,
        stored_file_name=stored_file_name,
        file_size=total_bytes,
        content_type=upload_file.content_type or "application/octet-stream",
        path=storage_key,
        public_url=f"/figure/{project_id}/{figure_id}",
        caption=normalized_caption,
        section=section,
        uploaded_at=datetime.now(timezone.utc),
    )

    try:
        add_figure(project_id, owner_uid, figure)
    except Exception:
        object_storage.delete(storage_key)
        raise

    logger.info("Stored figure %s for project %s", figure.id, project_id)
    return figure
