from __future__ import annotations

import re
from typing import Iterable

from app.core.exceptions import ProjectContentValidationError
from app.models.generation import IEEESectionMap, ResearchPaperSchema
from app.models.project import DISPLAY_SECTION_ORDER, build_display_paper_text

IEEE_SECTION_HEADINGS = {
    "abstract": re.compile(r"^abstract$", re.IGNORECASE),
    "keywords_inline": re.compile(r"^index terms\s*[-:]\s*(.*)$", re.IGNORECASE),
    "keywords_heading": re.compile(r"^index terms$", re.IGNORECASE),
    "introduction": re.compile(r"^(?:i\.?\s*)?introduction$", re.IGNORECASE),
    "related_work": re.compile(r"^(?:ii\.?\s*)?related work$", re.IGNORECASE),
    "methodology": re.compile(r"^(?:iii\.?\s*)?methodology$", re.IGNORECASE),
    "results": re.compile(r"^(?:iv\.?\s*)?results$", re.IGNORECASE),
    "discussion": re.compile(r"^(?:v\.?\s*)?discussion$", re.IGNORECASE),
    "limitations": re.compile(r"^(?:vi\.?\s*)?limitations$", re.IGNORECASE),
    "conclusion": re.compile(r"^(?:vii\.?\s*)?conclusion$", re.IGNORECASE),
    "references": re.compile(r"^references$", re.IGNORECASE),
}

BODY_SECTION_KEYS = tuple(key for _, key, _ in DISPLAY_SECTION_ORDER)
DISPLAY_SECTION_LABELS = {key: heading.title() for _, key, heading in DISPLAY_SECTION_ORDER}


def _normalize_keywords(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _normalize_paragraph_block(lines: list[str]) -> str:
    joined = "\n".join(line.rstrip() for line in lines).strip()
    if not joined:
        return ""

    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", joined):
        collapsed = " ".join(segment.strip() for segment in paragraph.splitlines() if segment.strip())
        if collapsed:
            paragraphs.append(collapsed)
    return "\n\n".join(paragraphs)


def build_editor_display_text(paper: ResearchPaperSchema) -> str:
    return build_display_paper_text(paper)


def build_latex_ready_text(paper: ResearchPaperSchema) -> str:
    parts = [
        "\\begin{abstract}",
        paper.abstract.strip(),
        "\\end{abstract}",
        "",
        "\\begin{IEEEkeywords}",
        ", ".join(paper.keywords),
        "\\end{IEEEkeywords}",
        "",
    ]

    for _, key, heading in DISPLAY_SECTION_ORDER:
        parts.extend([f"\\section{{{heading.title()}}}", getattr(paper.sections, key).strip(), ""])

    parts.append("\\begin{thebibliography}{00}")
    for index, reference in enumerate(paper.references or ["[1] Reference curation pending manual review."], start=1):
        reference_text = reference.strip()
        if reference_text.startswith(f"[{index}]"):
            reference_text = reference_text[len(f"[{index}]") :].strip()
        parts.append(f"\\bibitem{{ref{index}}} {reference_text}")
    parts.append("\\end{thebibliography}")
    return "\n".join(parts).strip()


def validate_research_paper(
    paper: ResearchPaperSchema,
    *,
    require_references: bool = False,
) -> list[str]:
    issues: list[str] = []

    if not paper.title.strip():
        issues.append("title is empty")
    if not paper.abstract.strip():
        issues.append("abstract is empty")
    if not paper.keywords:
        issues.append("keywords are missing")

    for key in BODY_SECTION_KEYS:
        value = getattr(paper.sections, key).strip()
        if not value:
            issues.append(f"section '{key}' is empty")

    if require_references and not paper.references:
        issues.append("references are missing")

    return issues


def parse_editor_content(
    *,
    title: str,
    content: str,
    fallback_keywords: list[str] | None = None,
    fallback_references: list[str] | None = None,
) -> ResearchPaperSchema:
    normalized_title = title.strip()
    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized_title:
        raise ProjectContentValidationError("Paper title is required.")
    if not normalized_content:
        raise ProjectContentValidationError("Paper content is required.")

    buffers: dict[str, list[str]] = {
        "abstract": [],
        "introduction": [],
        "related_work": [],
        "methodology": [],
        "results": [],
        "discussion": [],
        "limitations": [],
        "conclusion": [],
        "references": [],
    }
    keywords_line = ""
    current_section: str | None = None

    for raw_line in normalized_content.split("\n"):
        line = raw_line.strip()

        if IEEE_SECTION_HEADINGS["abstract"].match(line):
            current_section = "abstract"
            continue

        keywords_inline_match = IEEE_SECTION_HEADINGS["keywords_inline"].match(line)
        if keywords_inline_match:
            keywords_line = keywords_inline_match.group(1).strip()
            current_section = "keywords"
            continue

        if IEEE_SECTION_HEADINGS["keywords_heading"].match(line):
            current_section = "keywords"
            continue

        matched_heading = None
        for key in (*BODY_SECTION_KEYS, "references"):
            if IEEE_SECTION_HEADINGS[key].match(line):
                matched_heading = key
                break

        if matched_heading is not None:
            current_section = matched_heading
            continue

        if current_section == "keywords":
            if line:
                keywords_line = f"{keywords_line} {line}".strip() if keywords_line else line
            continue

        if current_section is not None:
            buffers[current_section].append(raw_line)

    parsed_keywords = _normalize_keywords(
        [keyword.strip() for keyword in keywords_line.split(",")] if keywords_line else (fallback_keywords or [])
    )
    parsed_references = [line.strip() for line in buffers["references"] if line.strip()]
    if not parsed_references:
        parsed_references = _normalize_keywords(fallback_references or [])

    normalized_sections = {
        "abstract": _normalize_paragraph_block(buffers["abstract"]),
        "introduction": _normalize_paragraph_block(buffers["introduction"]),
        "related_work": _normalize_paragraph_block(buffers["related_work"]),
        "methodology": _normalize_paragraph_block(buffers["methodology"]),
        "results": _normalize_paragraph_block(buffers["results"]),
        "discussion": _normalize_paragraph_block(buffers["discussion"]),
        "limitations": _normalize_paragraph_block(buffers["limitations"]),
        "conclusion": _normalize_paragraph_block(buffers["conclusion"]),
    }

    missing = [
        "Abstract" if key == "abstract" else DISPLAY_SECTION_LABELS[key]
        for key, value in normalized_sections.items()
        if not value
    ]
    if missing:
        raise ProjectContentValidationError(
            "Keep the IEEE manuscript headings intact. Missing or empty sections: " + ", ".join(missing)
        )

    if not parsed_keywords:
        raise ProjectContentValidationError(
            "Index Terms are required in the paper body. Keep the 'Index Terms' line in the editor."
        )

    return ResearchPaperSchema(
        title=normalized_title,
        abstract=normalized_sections["abstract"],
        keywords=parsed_keywords,
        sections=IEEESectionMap(
            introduction=normalized_sections["introduction"],
            related_work=normalized_sections["related_work"],
            methodology=normalized_sections["methodology"],
            results=normalized_sections["results"],
            discussion=normalized_sections["discussion"],
            limitations=normalized_sections["limitations"],
            conclusion=normalized_sections["conclusion"],
        ),
        references=parsed_references,
    )

