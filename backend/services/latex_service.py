from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.models.project import ProjectRecord
from app.services.project_service import get_effective_paper, get_project_title
from core.exceptions import ExportDependencyError, ExportError

logger = logging.getLogger("papereasy.backend.latex")

SECTION_ORDER = (
    ("introduction", "Introduction"),
    ("related_work", "Related Work"),
    ("methodology", "Methodology"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
)

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


def _to_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def escape_latex(value: str) -> str:
    ascii_value = _to_ascii(value)
    return "".join(LATEX_SPECIAL_CHARACTERS.get(character, character) for character in ascii_value)


def _normalize_text_for_latex(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs: list[str] = []
    for paragraph in normalized.split("\n\n"):
        line = " ".join(segment.strip() for segment in paragraph.splitlines() if segment.strip())
        if line:
            paragraphs.append(escape_latex(line))

    return "\n\n".join(paragraphs) if paragraphs else "No content provided."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "research-paper"


def _normalize_author_block(author_value: str) -> dict[str, object]:
    parts = [part.strip() for part in author_value.split(",") if part.strip()]
    if not parts:
        return {
            "name": escape_latex("PaperEasy Research Team"),
            "affiliation_lines": [escape_latex("Researchflow AI")],
        }

    name = escape_latex(parts[0])
    affiliation_parts = [escape_latex(part) for part in parts[1:]]
    if not affiliation_parts:
        affiliation_parts = [escape_latex("Independent Researcher")]

    return {
        "name": name,
        "affiliation_lines": affiliation_parts,
    }


def _build_author_blocks(project: ProjectRecord) -> list[dict[str, object]]:
    if project.authors:
        return [_normalize_author_block(author_value) for author_value in project.authors]

    return [
        {
            "name": escape_latex("PaperEasy Research Team"),
            "affiliation_lines": [escape_latex("Researchflow AI")],
        }
    ]


def _build_sections(
    project: ProjectRecord,
    figures_by_section: dict[str, list[dict[str, str]]],
) -> list[dict[str, object]]:
    paper = get_effective_paper(project)
    section_entries: list[dict[str, object]] = []

    for key, heading in SECTION_ORDER:
        section_entries.append(
            {
                "key": key,
                "heading": heading,
                "content": _normalize_text_for_latex(getattr(paper.sections, key)),
                "figures": figures_by_section.get(key, []),
            }
        )

    return section_entries


def _copy_template_assets(template_dir: Path, work_dir: Path) -> None:
    for asset_name in ("IEEEtran.cls",):
        source = template_dir / asset_name
        if not source.exists():
            continue
        shutil.copy2(source, work_dir / asset_name)


def generate_latex(
    project: ProjectRecord,
    template_dir: Path,
    work_dir: Path,
    figures_by_section: dict[str, list[dict[str, str]]] | None = None,
) -> LatexBuildResult:
    environment = _get_jinja_environment(template_dir)

    try:
        template = environment.get_template("ieee_template.tex")
    except Exception as exc:
        raise ExportError("Unable to load the IEEE LaTeX template.") from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    _copy_template_assets(template_dir, work_dir)

    paper = get_effective_paper(project)
    title = get_project_title(project)
    base_name = _slugify(title)
    tex_path = work_dir / f"{base_name}.tex"
    figures = figures_by_section or {"abstract": [], **{key: [] for key, _ in SECTION_ORDER}}

    context = {
        "title": escape_latex(title),
        "authors": _build_author_blocks(project),
        "keywords": [escape_latex(keyword) for keyword in paper.keywords],
        "abstract": _normalize_text_for_latex(paper.abstract),
        "sections": _build_sections(project, figures),
        "references": [escape_latex(reference) for reference in paper.references],
        "figures": figures,
    }

    try:
        content = template.render(**context)
    except Exception as exc:
        raise ExportError("Unable to render the IEEE LaTeX document.") from exc

    tex_path.write_text(content, encoding="utf-8")
    logger.info("Generated IEEE LaTeX export for project %s at %s", project.id, tex_path)

    return LatexBuildResult(
        work_dir=work_dir,
        tex_path=tex_path,
        file_name=tex_path.name,
        content=content,
    )

