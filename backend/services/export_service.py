from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from uuid import uuid4

from app.models.project import ExportArtifact, ExportFormat, ProjectRecord
from app.services.project_service import (
    get_effective_paper,
    get_project,
    get_project_title,
    record_export,
)
from core.config import get_settings
from core.exceptions import ExportDependencyError, ExportError
from persistence import get_object_storage
from services.latex_service import escape_latex, generate_latex

logger = logging.getLogger("papereasy.backend.export")
settings = get_settings()

MEDIA_TYPES: dict[ExportFormat, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "latex": "application/x-tex",
}

SECTION_ORDER = (
    ("Introduction", "introduction"),
    ("Related Work", "related_work"),
    ("Methodology", "methodology"),
    ("Results", "results"),
    ("Discussion", "discussion"),
    ("Limitations", "limitations"),
    ("Conclusion", "conclusion"),
)
FIGURE_SECTION_KEYS = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)


@dataclass(frozen=True)
class ExportedFile:
    artifact: ExportArtifact
    media_type: str
    content: bytes


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "research-paper"


def _artifact_download_url(project_id: str, artifact_id: str) -> str:
    return f"/export/{project_id}/{artifact_id}"


def _create_artifact(
    *,
    project_id: str,
    artifact_id: str,
    storage_key: str,
    export_format: ExportFormat,
    file_name: str,
) -> ExportArtifact:
    return ExportArtifact(
        id=artifact_id,
        format=export_format,
        file_name=file_name,
        path=storage_key,
        download_url=_artifact_download_url(project_id, artifact_id),
        created_at=datetime.now(timezone.utc),
    )


def _create_work_dir(project_id: str) -> Path:
    work_dir = settings.temp_dir / "exports" / project_id / str(uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _make_figure_label(figure_id: str, caption: str) -> str:
    caption_slug = re.sub(r"[^a-zA-Z0-9]+", "-", caption).strip("-").lower()
    base = caption_slug or figure_id
    return f"{base}-{figure_id[:8]}"


def _stage_figures(project: ProjectRecord, work_dir: Path):
    object_storage = get_object_storage()
    figures_by_section: dict[str, list[dict[str, str]]] = {
        key: [] for key in FIGURE_SECTION_KEYS
    }
    figure_paths_by_id: dict[str, Path] = {}

    for figure in project.figures:
        staged_path = work_dir / "figures" / figure.stored_file_name
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        object_storage.download_to_path(figure.path, staged_path)
        figure_paths_by_id[figure.id] = staged_path
        figures_by_section.setdefault(figure.section, []).append(
            {
                "id": figure.id,
                "caption": escape_latex(figure.caption),
                "label": _make_figure_label(figure.id, figure.caption),
                "path": staged_path.relative_to(work_dir).as_posix(),
            }
        )

    return figures_by_section, figure_paths_by_id


def _write_docx(project: ProjectRecord, output_dir: Path, figure_paths_by_id: dict[str, Path]) -> Path:
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches
    except ImportError as exc:
        raise ExportDependencyError("python-docx is required for DOCX export.") from exc

    paper = get_effective_paper(project)
    title = get_project_title(project)
    file_name = f"{_slugify(title)}.docx"
    output_path = output_dir / file_name

    document = Document()
    document.add_heading(title, 0)

    if project.authors:
        authors_paragraph = document.add_paragraph("; ".join(project.authors))
        authors_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    document.add_heading("Abstract", level=1)
    document.add_paragraph(paper.abstract)

    if paper.keywords:
        document.add_paragraph(f"Index Terms: {', '.join(paper.keywords)}")

    for heading, key in SECTION_ORDER:
        document.add_heading(heading, level=1)
        document.add_paragraph(getattr(paper.sections, key))

        section_figures = [figure for figure in project.figures if figure.section == key]
        for index, figure in enumerate(section_figures, start=1):
            figure_path = figure_paths_by_id.get(figure.id)
            if figure_path is None:
                continue

            try:
                document.add_picture(str(figure_path), width=Inches(5.75))
            except Exception as exc:
                raise ExportError(
                    f"Unable to embed figure '{figure.original_file_name}' in the DOCX export."
                ) from exc

            caption = document.add_paragraph()
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = caption.add_run(f"Figure {index}. {figure.caption}")
            run.italic = True

    document.add_heading("References", level=1)
    if paper.references:
        for reference in paper.references:
            document.add_paragraph(reference)
    else:
        document.add_paragraph("[1] Reference curation pending author review.")

    document.save(output_path)
    return output_path


def _run_pdflatex(tex_path: Path) -> Path:
    pdflatex_binary = which(settings.pdflatex_command)
    if pdflatex_binary is None:
        raise ExportDependencyError(
            "pdflatex is not installed or not available on PATH for PDF export."
        )

    command = [
        pdflatex_binary,
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]

    try:
        process = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            timeout=settings.pdflatex_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExportError("pdflatex timed out while generating the PDF export.") from exc

    if process.returncode != 0:
        compiler_output = (process.stderr.strip() or process.stdout.strip()).splitlines()
        detail = compiler_output[-12:] if compiler_output else ["pdflatex failed to compile the document."]
        raise ExportError("pdflatex failed: " + " | ".join(detail))

    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise ExportError("pdflatex completed without producing a PDF file.")

    for extension in (".aux", ".log", ".out"):
        auxiliary = tex_path.with_suffix(extension)
        if auxiliary.exists():
            auxiliary.unlink(missing_ok=True)

    return pdf_path


def _store_export(
    *,
    project: ProjectRecord,
    owner_uid: str,
    file_path: Path,
    export_format: ExportFormat,
    media_type: str,
) -> ExportedFile:
    artifact_id = str(uuid4())
    storage_key = f"outputs/{project.id}/{artifact_id}/{file_path.name}"
    object_storage = get_object_storage()
    object_storage.upload_file(storage_key, file_path, content_type=media_type)
    artifact = _create_artifact(
        project_id=project.id,
        artifact_id=artifact_id,
        storage_key=storage_key,
        export_format=export_format,
        file_name=file_path.name,
    )

    try:
        record_export(project.id, owner_uid, artifact)
    except Exception:
        object_storage.delete(storage_key)
        raise

    logger.info("Generated %s export for project %s at %s", export_format, project.id, storage_key)
    return ExportedFile(
        artifact=artifact,
        media_type=media_type,
        content=file_path.read_bytes(),
    )


def _cleanup_work_dir(work_dir: Path) -> None:
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        logger.warning("Unable to clean temporary export directory %s", work_dir)


def export_project_latex(project_id: str, owner_uid: str) -> ExportedFile:
    project = get_project(project_id, owner_uid)
    work_dir = _create_work_dir(project_id)
    try:
        figures_by_section, _ = _stage_figures(project, work_dir)
        build_result = generate_latex(project, settings.templates_dir, work_dir, figures_by_section)
        return _store_export(
            project=project,
            owner_uid=owner_uid,
            file_path=build_result.tex_path,
            export_format="latex",
            media_type=MEDIA_TYPES["latex"],
        )
    finally:
        _cleanup_work_dir(work_dir)


def export_project_docx(project_id: str, owner_uid: str) -> ExportedFile:
    project = get_project(project_id, owner_uid)
    get_effective_paper(project)
    work_dir = _create_work_dir(project_id)
    try:
        _, figure_paths_by_id = _stage_figures(project, work_dir)
        file_path = _write_docx(project, work_dir, figure_paths_by_id)
        return _store_export(
            project=project,
            owner_uid=owner_uid,
            file_path=file_path,
            export_format="docx",
            media_type=MEDIA_TYPES["docx"],
        )
    finally:
        _cleanup_work_dir(work_dir)


def export_project_pdf(project_id: str, owner_uid: str) -> ExportedFile:
    project = get_project(project_id, owner_uid)
    work_dir = _create_work_dir(project_id)
    try:
        figures_by_section, _ = _stage_figures(project, work_dir)
        build_result = generate_latex(project, settings.templates_dir, work_dir, figures_by_section)
        pdf_path = _run_pdflatex(build_result.tex_path)
        return _store_export(
            project=project,
            owner_uid=owner_uid,
            file_path=pdf_path,
            export_format="pdf",
            media_type=MEDIA_TYPES["pdf"],
        )
    finally:
        _cleanup_work_dir(work_dir)
