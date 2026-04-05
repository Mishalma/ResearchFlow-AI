from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from app.core.exceptions import ExtractionError, UnsupportedFileTypeError
from app.utils.text_cleaner import clean_extracted_text

logger = logging.getLogger("papereasy.backend.extraction_service")


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    extraction_time_ms: float


def extract_text(file_path: Path) -> ExtractionResult:
    start_time = perf_counter()
    extension = file_path.suffix.lower()

    if extension == ".pdf":
        extracted_text = _extract_pdf_text(file_path)
    elif extension == ".docx":
        extracted_text = _extract_docx_text(file_path)
    else:
        raise UnsupportedFileTypeError()

    cleaned_text = clean_extracted_text(extracted_text)
    if not cleaned_text:
        raise ExtractionError("Unable to extract text from the uploaded file.")

    duration_ms = (perf_counter() - start_time) * 1000
    logger.info("Extracted text from %s in %.2f ms", file_path.name, duration_ms)

    return ExtractionResult(text=cleaned_text, extraction_time_ms=duration_ms)


def _extract_pdf_text(file_path: Path) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise ExtractionError("PDF extraction dependency is not installed.") from exc

    try:
        with fitz.open(file_path) as document:
            return "\n".join(page.get_text() for page in document)
    except fitz.FileDataError as exc:
        raise ExtractionError(
            "Unable to extract text from the PDF file. The PDF may be corrupted."
        ) from exc
    except Exception as exc:
        raise ExtractionError("Unable to extract text from the PDF file.") from exc


def _extract_docx_text(file_path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ExtractionError("DOCX extraction dependency is not installed.") from exc

    try:
        document = Document(file_path)
    except Exception as exc:
        raise ExtractionError("Unable to extract text from the DOCX file.") from exc

    return "\n".join(paragraph.text for paragraph in document.paragraphs)
