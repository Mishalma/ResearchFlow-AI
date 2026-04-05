from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.models.project import ProjectRecord
from app.services.project_service import (
    get_effective_sections,
    get_project_references,
    get_project_title,
)
from core.exceptions import ExportDependencyError, ExportError

logger = logging.getLogger("papereasy.backend.latex")

SECTION_KEYS = ("abstract", "introduction", "methodology", "conclusion")

LATEX_SPECIAL_CHARACTERS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class LatexBuildResult:
    export_id: str
    work_dir: Path
    tex_path: Path
    file_name: str
    content: str


def _get_jinja_environment(template_dir: Path):
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:
        raise ExportDependencyError("Jinja2 is required for LaTeX export.") from exc

    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )


def escape_latex(value: str) -> str:
    return "".join(LATEX_SPECIAL_CHARACTERS.get(character, character) for character in value)


def _normalize_text_for_latex(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = []
    for paragraph in normalized.split("\n\n"):
        line = " ".join(segment.strip() for segment in paragraph.splitlines() if segment.strip())
        if line:
            paragraphs.append(escape_latex(line))

    return "\n\n".join(paragraphs) if paragraphs else "No content provided."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "research-paper"


def _build_figures_by_section(project: ProjectRecord, work_dir: Path) -> dict[str, list[dict[str, str]]]:
    figures_by_section: dict[str, list[dict[str, str]]] = {
        key: [] for key in SECTION_KEYS
    }

    backend_root = Path(__file__).resolve().parents[1]

    for figure in project.figures:
        absolute_path = Path(figure.path)
        if not absolute_path.is_absolute():
            absolute_path = (backend_root / figure.path).resolve()

        if not absolute_path.exists():
            logger.warning(
                "Skipping missing figure %s while rendering LaTeX for project %s",
                figure.id,
                project.id,
            )
            continue

        relative_path = Path(os.path.relpath(absolute_path, work_dir)).as_posix()
        figures_by_section[figure.section].append(
            {
                "id": figure.id,
                "caption": escape_latex(figure.caption),
                "path": relative_path,
            }
        )

    return figures_by_section


def generate_latex(
    project: ProjectRecord,
    template_dir: Path,
    outputs_dir: Path,
) -> LatexBuildResult:
    sections = get_effective_sections(project)
    environment = _get_jinja_environment(template_dir)

    try:
        template = environment.get_template("ieee_template.tex")
    except Exception as exc:
        raise ExportError("Unable to load the IEEE LaTeX template.") from exc

    export_id = str(uuid4())
    work_dir = outputs_dir / project.id / export_id
    work_dir.mkdir(parents=True, exist_ok=True)

    title = get_project_title(project)
    base_name = _slugify(title)
    tex_path = work_dir / f"{base_name}.tex"

    context = {
        "title": escape_latex(title),
        "abstract": _normalize_text_for_latex(sections.abstract),
        "introduction": _normalize_text_for_latex(sections.introduction),
        "methodology": _normalize_text_for_latex(sections.methodology),
        "conclusion": _normalize_text_for_latex(sections.conclusion),
        "references": [escape_latex(reference) for reference in get_project_references(project)],
        "figures": _build_figures_by_section(project, work_dir),
    }

    try:
        content = template.render(**context)
    except Exception as exc:
        raise ExportError("Unable to render the IEEE LaTeX document.") from exc

    tex_path.write_text(content, encoding="utf-8")
    logger.info("Generated LaTeX export for project %s at %s", project.id, tex_path)

    return LatexBuildResult(
        export_id=export_id,
        work_dir=work_dir,
        tex_path=tex_path,
        file_name=tex_path.name,
        content=content,
    )
