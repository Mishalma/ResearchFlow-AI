from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    UnsupportedImageTypeError,
)

logger = logging.getLogger("papereasy.backend.figure")

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StoredFigure:
    figure: FigureRecord
    file_path: Path


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
    upload_file: UploadFile,
    caption: str,
    section: FigureSection,
    figures_dir: Path,
    max_size_bytes: int,
    max_size_mb: int,
) -> FigureRecord:
    get_project(project_id)
    original_file_name, extension = _normalize_image_filename(upload_file.filename)
    ensure_figure_dir(figures_dir)

    figure_id = str(uuid4())
    stored_file_name = f"{figure_id}{extension}"
    destination = figures_dir / stored_file_name
    total_bytes = 0

    try:
        with destination.open("wb") as file_buffer:
            while True:
                chunk = await upload_file.read(READ_CHUNK_SIZE)
                if not chunk:
                    break

                total_bytes += len(chunk)
                if total_bytes > max_size_bytes:
                    raise FileTooLargeError(max_size_mb)

                file_buffer.write(chunk)
    except FileTooLargeError:
        delete_file(destination)
        raise
    except OSError as exc:
        delete_file(destination)
        logger.exception("Unable to store figure %s", original_file_name)
        raise FigureStorageError() from exc
    finally:
        await upload_file.close()

    if total_bytes == 0:
        delete_file(destination)
        raise EmptyFileError()

    figure = FigureRecord(
        id=figure_id,
        original_file_name=original_file_name,
        stored_file_name=stored_file_name,
        file_size=total_bytes,
        content_type=upload_file.content_type or "application/octet-stream",
        path=(Path("static") / "figures" / stored_file_name).as_posix(),
        public_url=f"/static/figures/{stored_file_name}",
        caption=caption.strip(),
        section=section,
        uploaded_at=datetime.now(timezone.utc),
    )
    add_figure(project_id, figure)
    logger.info("Stored figure %s for project %s", figure.id, project_id)
    return figure
