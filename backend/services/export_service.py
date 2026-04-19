from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
from collections.abc import Iterable
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from uuid import uuid4
import zipfile

from app.models.project import ExportArtifact, ExportFormat, ProjectRecord
from app.services.project_service import (
    get_effective_paper,
    get_project,
    get_project_title,
    record_export,
)
from core.config import get_settings
from core.exceptions import ExportDependencyError, ExportError, PersistenceError
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
    artifact: ExportArtifact | None
    export_format: ExportFormat
    media_type: str
    content: bytes
    file_name: str
    persisted: bool = True
    persistence_warning: str | None = None


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
    tables_by_section: dict[str, list[dict[str, str]]] = {
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

    for entry in project.generated_figures:
        if not isinstance(entry, dict):
            continue
        spec = entry.get("spec") or {}
        if not isinstance(spec, dict):
            continue
        section = str(spec.get("section", "")).strip().lower()
        spec_id = str(spec.get("id", "")).strip()
        if not section or not spec_id:
            continue
        png_base64 = str(entry.get("png_base64") or "").strip()
        if png_base64:
            staged_path = work_dir / "figures" / f"{spec_id}.png"
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            staged_path.write_bytes(base64.b64decode(png_base64))
            figure_paths_by_id[spec_id] = staged_path
        figures_by_section.setdefault(section, []).append(
            {
                "id": spec_id,
                "caption": escape_latex(str(spec.get("caption", "")).strip()),
                "label": _make_figure_label(spec_id, str(spec.get("caption", "")).strip()),
                "path": f"figures/{spec_id}.png",
                "latex_block": str(entry.get("latex_block") or "").strip(),
                "png_base64": png_base64,
                "placement_hint": str(spec.get("placement_hint", "")).strip(),
                "spec": spec,
            }
        )

    for entry in project.generated_tables:
        if not isinstance(entry, dict):
            continue
        if not entry.get("render_success"):
            continue
        spec = entry.get("spec") or {}
        if not isinstance(spec, dict):
            continue
        section = str(spec.get("section", "")).strip().lower()
        spec_id = str(spec.get("id", "")).strip()
        if not section or not spec_id:
            continue
        tables_by_section.setdefault(section, []).append(
            {
                "id": spec_id,
                "caption": escape_latex(str(spec.get("caption", "")).strip()),
                "label": spec_id,
                "latex": str(entry.get("latex_table") or entry.get("latex_block") or "").strip(),
                "latex_block": str(entry.get("latex_block") or "").strip(),
                "placement_hint": str(spec.get("placement_hint", "")).strip(),
                "spec": spec,
            }
        )

    return figures_by_section, tables_by_section, figure_paths_by_id


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
        section_text = getattr(paper.sections, key)
        section_paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section_text) if part.strip()] or [section_text]
        generated_section_figures = [
            entry
            for entry in project.generated_figures
            if isinstance(entry, dict)
            and isinstance(entry.get("spec"), dict)
            and entry.get("render_success")
            and entry["spec"].get("section") == key
        ]
        generated_section_tables = [
            entry
            for entry in project.generated_tables
            if isinstance(entry, dict)
            and isinstance(entry.get("spec"), dict)
            and entry.get("render_success")
            and entry["spec"].get("section") == key
        ]

        inserted_generated_figure_ids: set[str] = set()
        inserted_generated_table_ids: set[str] = set()
        for paragraph_text in section_paragraphs:
            document.add_paragraph(paragraph_text)
            for entry in generated_section_figures:
                spec = entry.get("spec") or {}
                figure_id = str(spec.get("id", "")).strip()
                placement_hint = str(spec.get("placement_hint", "")).strip()
                if figure_id in inserted_generated_figure_ids:
                    continue
                if placement_hint and placement_hint not in paragraph_text:
                    continue
                figure_path = figure_paths_by_id.get(figure_id)
                if figure_path is None:
                    continue
                buffer = BytesIO(figure_path.read_bytes())
                document.add_picture(buffer, width=Inches(3.0))
                document.add_paragraph(str(spec.get("caption", "")).strip(), style="Caption")
                inserted_generated_figure_ids.add(figure_id)
            for entry in generated_section_tables:
                spec = entry.get("spec") or {}
                table_id = str(spec.get("id", "")).strip()
                placement_hint = str(spec.get("placement_hint", "")).strip()
                if table_id in inserted_generated_table_ids:
                    continue
                if placement_hint and placement_hint not in paragraph_text:
                    continue
                _append_generated_table(document, spec)
                inserted_generated_table_ids.add(table_id)

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

        for entry in generated_section_figures:
            spec = entry.get("spec") or {}
            figure_id = str(spec.get("id", "")).strip()
            if figure_id in inserted_generated_figure_ids:
                continue
            figure_path = figure_paths_by_id.get(figure_id)
            if figure_path is None:
                continue
            buffer = BytesIO(figure_path.read_bytes())
            document.add_picture(buffer, width=Inches(3.0))
            document.add_paragraph(str(spec.get("caption", "")).strip(), style="Caption")
            inserted_generated_figure_ids.add(figure_id)

        for entry in generated_section_tables:
            spec = entry.get("spec") or {}
            table_id = str(spec.get("id", "")).strip()
            if table_id in inserted_generated_table_ids:
                continue
            _append_generated_table(document, spec)
            inserted_generated_table_ids.add(table_id)

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
    content = file_path.read_bytes()

    try:
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
    except PersistenceError as exc:
        logger.warning(
            "Export persistence unavailable for project %s (%s). Returning direct %s download without stored artifact.",
            project.id,
            exc,
            export_format,
        )
        return ExportedFile(
            artifact=None,
            export_format=export_format,
            media_type=media_type,
            content=content,
            file_name=file_path.name,
            persisted=False,
            persistence_warning=str(exc),
        )

    logger.info("Generated %s export for project %s at %s", export_format, project.id, storage_key)
    return ExportedFile(
        artifact=artifact,
        export_format=export_format,
        media_type=media_type,
        content=content,
        file_name=file_path.name,
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
        figures_by_section, tables_by_section, _ = _stage_figures(project, work_dir)
        build_result = generate_latex(project, settings.templates_dir, work_dir, figures_by_section, tables_by_section)
        if project.generated_figures:
            zip_path = work_dir / f"{_slugify(get_project_title(project))}-latex.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(build_result.tex_path, arcname=build_result.tex_path.name)
                figures_dir = work_dir / "figures"
                if figures_dir.exists():
                    for asset in figures_dir.rglob("*"):
                        if asset.is_file():
                            archive.write(asset, arcname=asset.relative_to(work_dir).as_posix())
            return _store_export(
                project=project,
                owner_uid=owner_uid,
                file_path=zip_path,
                export_format="latex",
                media_type="application/zip",
            )
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
        _, _, figure_paths_by_id = _stage_figures(project, work_dir)
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
        figures_by_section, tables_by_section, _ = _stage_figures(project, work_dir)
        build_result = generate_latex(project, settings.templates_dir, work_dir, figures_by_section, tables_by_section)
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


def _append_generated_table(document, spec: dict[str, object]) -> None:
    headers = [str(value) for value in (spec.get("data", {}) or {}).get("headers", [])]
    rows = _normalize_table_rows_for_docx(
        (spec.get("data", {}) or {}).get("rows", []),
        column_count=len(headers),
    )
    if not headers:
        return

    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for index, header in enumerate(headers):
        header_cells[index].text = header

    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            if index < len(cells):
                cells[index].text = value

    document.add_paragraph(str(spec.get("caption", "")).strip(), style="Caption")


def _normalize_table_rows_for_docx(rows: object, *, column_count: int) -> list[list[str]]:
    normalized_rows: list[list[str]] = []
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, dict)):
        return normalized_rows

    for row in rows:
        if isinstance(row, dict):
            values = [str(value) for value in row.values()]
        elif isinstance(row, Iterable) and not isinstance(row, (str, bytes)):
            values = [str(cell) for cell in row]
        else:
            values = [str(row)]

        if column_count > 0:
            if len(values) < column_count:
                values.extend([""] * (column_count - len(values)))
            elif len(values) > column_count:
                values = values[:column_count]
        normalized_rows.append(values)
    return normalized_rows
