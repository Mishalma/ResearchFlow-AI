from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import UploadFile

from app.core.exceptions import (
    EmptyFileError,
    FileStorageError,
    FileTooLargeError,
    InvalidUploadError,
    UnsupportedFileTypeError,
)
from persistence.base import ObjectStorage

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
READ_CHUNK_SIZE = 1024 * 1024

logger = logging.getLogger("papereasy.backend.file_service")


@dataclass(frozen=True)
class StoredFile:
    project_id: str
    file_name: str
    local_path: Path
    file_type: str
    file_size: int
    content_type: str
    storage_key: str
    storage_uri: str


def ensure_upload_dir(upload_dir: Path) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)


def delete_file(file_path: Path) -> None:
    if file_path.exists():
        file_path.unlink(missing_ok=True)


def _normalize_filename(file_name: str | None) -> tuple[str, str]:
    normalized_file_name = Path(file_name or "").name
    if not normalized_file_name:
        raise InvalidUploadError()

    extension = Path(normalized_file_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError()

    return normalized_file_name, extension


async def store_upload_file(
    upload_file: UploadFile,
    upload_dir: Path,
    temp_dir: Path,
    object_storage: ObjectStorage,
    max_size_bytes: int,
    max_size_mb: int,
) -> StoredFile:
    file_name, extension = _normalize_filename(upload_file.filename)
    ensure_upload_dir(upload_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    project_id = str(uuid4())
    total_bytes = 0
    temp_path = Path(
        NamedTemporaryFile(
            delete=False,
            dir=temp_dir,
            prefix=f"upload-{project_id}-",
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
        logger.exception("Unable to stage uploaded file %s", file_name)
        raise FileStorageError() from exc
    finally:
        await upload_file.close()

    if total_bytes == 0:
        delete_file(temp_path)
        raise EmptyFileError()

    storage_key = f"uploads/{project_id}{extension}"
    try:
        stored_object = object_storage.upload_file(
            storage_key,
            temp_path,
            content_type=upload_file.content_type or "application/octet-stream",
        )
    except Exception:
        delete_file(temp_path)
        raise

    logger.info(
        "Stored upload %s as %s (%s bytes)",
        file_name,
        storage_key,
        total_bytes,
    )

    return StoredFile(
        project_id=project_id,
        file_name=file_name,
        local_path=temp_path,
        file_type=extension.lstrip("."),
        file_size=total_bytes,
        content_type=upload_file.content_type or "application/octet-stream",
        storage_key=storage_key,
        storage_uri=stored_object.storage_uri,
    )
