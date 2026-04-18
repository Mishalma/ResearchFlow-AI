from __future__ import annotations

import html
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.services.paper_service import build_editor_display_text, build_latex_ready_text, validate_research_paper
from core.config import Settings
from formatting.config import FormattingConfig
from formatting.schemas import CompilerDiagnostic, FormattingProfile
from models.generation import GeneratedPaper, ResearchPaperSchema

SECTION_ORDER = (
    ("introduction", "Introduction"),
    ("related_work", "Related Work"),
    ("methodology", "Methodology"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("limitations", "Limitations"),
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

REFERENCE_PREFIX_PATTERN = re.compile(r"^\[\d+\]\s*")


def escape_latex(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(LATEX_SPECIAL_CHARACTERS.get(character, character) for character in ascii_value)


def normalize_paragraphs_for_latex(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", normalized):
        collapsed = " ".join(segment.strip() for segment in paragraph.splitlines() if segment.strip())
        if collapsed:
            paragraphs.append(escape_latex(collapsed))
    return "\n\n".join(paragraphs)


def normalize_keywords(keywords: Iterable[str], *, sort_alpha: bool) -> list[str]:
    cleaned = [escape_latex(str(keyword).strip()) for keyword in keywords if str(keyword).strip()]
    if sort_alpha:
        cleaned = sorted(dict.fromkeys(cleaned), key=str.lower)
    return cleaned


def build_author_blocks(author_metadata: object | None) -> tuple[list[dict[str, object]], list[CompilerDiagnostic]]:
    warnings: list[CompilerDiagnostic] = []
    authors_value = None
    if isinstance(author_metadata, dict):
        authors_value = author_metadata.get("authors") or author_metadata.get("author_blocks")
    elif author_metadata not in (None, "", {}):
        authors_value = author_metadata

    author_blocks: list[dict[str, object]] = []
    if isinstance(authors_value, list):
        for entry in authors_value:
            if isinstance(entry, dict):
                name = escape_latex(str(entry.get("name", "")).strip())
                if not name:
                    continue
                affiliation_lines = [
                    escape_latex(str(item).strip())
                    for item in (
                        entry.get("affiliation_lines")
                        or entry.get("affiliations")
                        or entry.get("affiliation")
                        or []
                    )
                    if str(item).strip()
                ]
                email = escape_latex(str(entry.get("email", "")).strip()) if str(entry.get("email", "")).strip() else None
                orcid = escape_latex(str(entry.get("orcid", "")).strip()) if str(entry.get("orcid", "")).strip() else None
                author_blocks.append(
                    {
                        "name": name,
                        "affiliation_lines": affiliation_lines or [escape_latex("Independent Researcher")],
                        "email": email,
                        "orcid": orcid,
                    }
                )
            else:
                name = escape_latex(str(entry).strip())
                if name:
                    author_blocks.append(
                        {
                            "name": name,
                            "affiliation_lines": [escape_latex("Independent Researcher")],
                            "email": None,
                            "orcid": None,
                        }
                    )

    if not author_blocks:
        warnings.append(
            CompilerDiagnostic(
                severity="warning",
                category="missing_author_metadata",
                message="Author metadata was not provided. Using a placeholder IEEE author block for compilation.",
                retryable=False,
                remediation_target="upstream_content",
            )
        )
        author_blocks = [
            {
                "name": escape_latex("PaperEasy Research Team"),
                "affiliation_lines": [escape_latex("Independent Researcher")],
                "email": None,
                "orcid": None,
            }
        ]
    return author_blocks, warnings


def build_reference_entries(references: Iterable[str]) -> list[str]:
    entries: list[str] = []
    for reference in references:
        cleaned = str(reference).strip()
        if not cleaned:
            continue
        entries.append(escape_latex(REFERENCE_PREFIX_PATTERN.sub("", cleaned)))
    return entries


def build_section_entries(
    paper: ResearchPaperSchema,
    *,
    figures: dict[str, list[dict[str, object]]] | None = None,
    tables: dict[str, list[dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    resolved_figures = figures or {}
    resolved_tables = tables or {}
    entries: list[dict[str, object]] = []
    for section_key, heading in SECTION_ORDER:
        entries.append(
            {
                "key": section_key,
                "heading": heading,
                "content": normalize_paragraphs_for_latex(getattr(paper.sections, section_key)),
                "html_content": html.escape(getattr(paper.sections, section_key)).replace("\n", "<br />"),
                "figures": resolved_figures.get(section_key, []),
                "tables": resolved_tables.get(section_key, []),
            }
        )
    return entries


def build_preview_section_entries(
    paper: ResearchPaperSchema,
    *,
    figures: dict[str, list[dict[str, object]]] | None = None,
    tables: dict[str, list[dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    resolved_figures = figures or {}
    resolved_tables = tables or {}
    entries: list[dict[str, object]] = []
    for section_key, heading in SECTION_ORDER:
        entries.append(
            {
                "key": section_key,
                "heading": heading,
                "content_html": format_html_paragraphs(getattr(paper.sections, section_key)),
                "figures": resolved_figures.get(section_key, []),
                "tables": resolved_tables.get(section_key, []),
            }
        )
    return entries


def build_document_context(
    *,
    paper: ResearchPaperSchema,
    profile: FormattingProfile,
    author_blocks: list[dict[str, object]],
    figures: dict[str, list[dict[str, object]]] | None = None,
    tables: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    abstract_text = paper.abstract.strip()
    return {
        "profile": profile,
        "title": escape_latex(paper.title),
        "title_html": html.escape(paper.title),
        "authors": author_blocks,
        "keywords": normalize_keywords(paper.keywords, sort_alpha=profile.sort_index_terms),
        "keywords_html": [html.escape(keyword) for keyword in sorted(paper.keywords, key=str.lower) if keyword.strip()],
        "abstract": normalize_paragraphs_for_latex(abstract_text),
        "abstract_html": format_html_paragraphs(abstract_text),
        "sections": build_section_entries(paper, figures=figures, tables=tables),
        "preview_sections": build_preview_section_entries(paper, figures=figures, tables=tables),
        "references": build_reference_entries(paper.references),
        "references_html": [html.escape(reference.strip()) for reference in paper.references if reference.strip()],
    }


def validate_input_content(
    *,
    paper: ResearchPaperSchema,
    config: FormattingConfig,
    author_warnings: list[CompilerDiagnostic] | None = None,
) -> list[CompilerDiagnostic]:
    diagnostics = list(author_warnings or [])
    issues = validate_research_paper(paper, require_references=True)
    for issue in issues:
        diagnostics.append(
            CompilerDiagnostic(
                severity="error",
                category="invalid_input",
                message=issue,
                retryable=True,
                remediation_target="upstream_content",
            )
        )
    abstract_word_count = len(paper.abstract.split())
    if abstract_word_count < config.abstract_min_words or abstract_word_count > config.abstract_max_words:
        diagnostics.append(
            CompilerDiagnostic(
                severity="warning",
                category="abstract_length",
                message=(
                    f"Abstract word count is {abstract_word_count}; IEEE conference abstracts usually target "
                    f"{config.abstract_min_words}-{config.abstract_max_words} words."
                ),
                retryable=True,
                remediation_target="upstream_content",
            )
        )
    if not paper.keywords:
        diagnostics.append(
            CompilerDiagnostic(
                severity="warning",
                category="missing_keywords",
                message="Index terms are missing; IEEE conference output normally includes them.",
                retryable=True,
                remediation_target="upstream_content",
            )
        )
    return diagnostics


def build_legacy_paper_snapshot(paper: ResearchPaperSchema) -> GeneratedPaper:
    return GeneratedPaper(
        paper=paper,
        formatted_text=build_editor_display_text(paper),
        latex_ready=build_latex_ready_text(paper),
    )


def create_work_dir(settings: Settings, trace_id: str) -> Path:
    work_dir = settings.temp_dir / "formatting" / trace_id / str(uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def copy_support_assets(*, config: FormattingConfig, work_dir: Path) -> None:
    asset_dir = config.support_asset_dir
    if asset_dir is None:
        return
    for asset_name in ("IEEEtran.cls",):
        source = Path(asset_dir) / asset_name
        if source.exists():
            shutil.copy2(source, work_dir / asset_name)


def maybe_cleanup_work_dir(*, work_dir: Path, should_cleanup: bool) -> None:
    if should_cleanup:
        shutil.rmtree(work_dir, ignore_errors=True)


def format_html_paragraphs(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", normalized):
        collapsed = " ".join(segment.strip() for segment in paragraph.splitlines() if segment.strip())
        if collapsed:
            paragraphs.append(f"<p>{html.escape(collapsed)}</p>")
    return "\n".join(paragraphs)


def summarize_diagnostics(diagnostics: Iterable[CompilerDiagnostic]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for diagnostic in diagnostics:
        key = f"{diagnostic.severity}:{diagnostic.category}"
        summary[key] = summary.get(key, 0) + 1
    return summary
