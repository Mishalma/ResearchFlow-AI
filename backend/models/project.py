from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from models.generation import GeneratedPaper, GenerationMetadata, IEEESectionMap, ResearchPaperSchema

FigureSection = Literal[
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
]
ExportFormat = Literal["pdf", "docx", "latex"]

DISPLAY_SECTION_ORDER = (
    ("I.", "introduction", "INTRODUCTION"),
    ("II.", "related_work", "RELATED WORK"),
    ("III.", "methodology", "METHODOLOGY"),
    ("IV.", "results", "RESULTS"),
    ("V.", "discussion", "DISCUSSION"),
    ("VI.", "limitations", "LIMITATIONS"),
    ("VII.", "conclusion", "CONCLUSION"),
)

LEGACY_SECTION_FALLBACKS = {
    "abstract": "Abstract content requires author review.",
    "introduction": "Introduction content requires author review.",
    "related_work": "Related work was not explicitly identified in the source material and requires author review.",
    "methodology": "Methodology content requires author review.",
    "results": "Results were not explicitly identified in the source material and require author review.",
    "discussion": "Discussion points were not explicitly identified in the source material and require author review.",
    "limitations": "Limitations content requires author review.",
    "conclusion": "Conclusion content requires author review.",
}

BODY_SECTION_FIELDS = tuple(field for _, field, _ in DISPLAY_SECTION_ORDER)


def _default_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        candidates = value.splitlines()
    elif isinstance(value, Iterable):
        candidates = [str(item) for item in value]
    else:
        candidates = [str(value)]

    normalized: list[str] = []
    for item in candidates:
        cleaned = item.strip()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _fallback_text(key: str) -> str:
    return LEGACY_SECTION_FALLBACKS.get(key, f"{key.replace('_', ' ').title()} content requires author review.")


def build_display_paper_text(paper: ResearchPaperSchema) -> str:
    parts = [
        "Abstract",
        paper.abstract.strip(),
        "",
        f"Index Terms - {', '.join(paper.keywords).strip() or 'research paper generation'}",
        "",
    ]

    for numeral, key, heading in DISPLAY_SECTION_ORDER:
        section_text = getattr(paper.sections, key).strip()
        parts.extend([f"{numeral} {heading}", section_text, ""])

    parts.append("References")
    if paper.references:
        parts.extend(reference.strip() for reference in paper.references if reference.strip())
    else:
        parts.append("[1] Reference curation pending author review.")

    return "\n".join(part for part in parts if part is not None).strip()


def _coerce_sections(value: object) -> IEEESectionMap | None:
    if value is None:
        return None

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")

    if not isinstance(value, Mapping):
        return None

    normalized = {
        "introduction": _clean_text(value.get("introduction")),
        "related_work": _clean_text(value.get("related_work")),
        "methodology": _clean_text(value.get("methodology")),
        "results": _clean_text(value.get("results")),
        "discussion": _clean_text(value.get("discussion")),
        "limitations": _clean_text(value.get("limitations")),
        "conclusion": _clean_text(value.get("conclusion")),
    }

    legacy_any = any(
        _clean_text(value.get(key))
        for key in ("abstract", "introduction", "methodology", "conclusion")
    )
    any_content = any(normalized.values()) or legacy_any
    if not any_content:
        return None

    return IEEESectionMap(
        introduction=normalized["introduction"] or _fallback_text("introduction"),
        related_work=normalized["related_work"] or _fallback_text("related_work"),
        methodology=normalized["methodology"] or _fallback_text("methodology"),
        results=normalized["results"] or _fallback_text("results"),
        discussion=normalized["discussion"] or _fallback_text("discussion"),
        limitations=normalized["limitations"] or _fallback_text("limitations"),
        conclusion=normalized["conclusion"] or _fallback_text("conclusion"),
    )


def _coerce_paper(
    value: object,
    *,
    default_title: str,
    default_keywords: list[str],
) -> ResearchPaperSchema | None:
    if value is None:
        return None

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")

    if not isinstance(value, Mapping):
        return None

    if "paper" in value and isinstance(value.get("paper"), Mapping):
        value = value["paper"]

    sections = _coerce_sections(value.get("sections") if "sections" in value else value)
    has_any_content = bool(_clean_text(value.get("abstract"))) or sections is not None
    if not has_any_content:
        return None

    return ResearchPaperSchema(
        title=_clean_text(value.get("title")) or default_title,
        abstract=_clean_text(value.get("abstract")) or _fallback_text("abstract"),
        keywords=_normalize_string_list(value.get("keywords")) or list(default_keywords),
        sections=sections
        or IEEESectionMap(
            introduction=_fallback_text("introduction"),
            related_work=_fallback_text("related_work"),
            methodology=_fallback_text("methodology"),
            results=_fallback_text("results"),
            discussion=_fallback_text("discussion"),
            limitations=_fallback_text("limitations"),
            conclusion=_fallback_text("conclusion"),
        ),
        references=_normalize_string_list(value.get("references")),
    )


def _coerce_generated_paper(
    value: object,
    *,
    default_title: str,
    default_keywords: list[str],
    fallback_content: str,
) -> GeneratedPaper | None:
    paper = _coerce_paper(value, default_title=default_title, default_keywords=default_keywords)
    if paper is None:
        return None

    raw_mapping: Mapping[str, object] = {}
    if isinstance(value, BaseModel):
        raw_mapping = value.model_dump(mode="python")
    elif isinstance(value, Mapping):
        raw_mapping = value

    formatted_text = (
        _clean_text(raw_mapping.get("formatted_text"))
        or _clean_text(raw_mapping.get("formatted_paper"))
        or fallback_content
        or build_display_paper_text(paper)
    )
    latex_ready = _clean_text(raw_mapping.get("latex_ready")) or formatted_text

    return GeneratedPaper(
        paper=paper,
        formatted_text=formatted_text,
        latex_ready=latex_ready,
    )


class FigureRecord(BaseModel):
    id: str
    original_file_name: str
    stored_file_name: str
    file_size: int = Field(ge=0)
    content_type: str
    path: str
    public_url: str
    caption: str = Field(min_length=1)
    section: FigureSection
    uploaded_at: datetime


class ExportArtifact(BaseModel):
    id: str
    format: ExportFormat
    file_name: str
    path: str
    download_url: str
    created_at: datetime


class ProjectRecord(BaseModel):
    id: str
    file_name: str
    file_path: str
    extracted_text: str
    file_type: str
    file_size: int = Field(ge=0)
    extraction_time_ms: float = Field(ge=0)
    title: str = Field(default="Untitled Project", min_length=1)
    owner_uid: str = Field(default="")
    owner_email: str = Field(default="")
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    content: str = Field(default="")
    display_paper_text: str = Field(default="")
    latex_ready: str = Field(default="")
    generated_paper: GeneratedPaper | None = None
    edited_paper: ResearchPaperSchema | None = None
    figures: list[FigureRecord] = Field(default_factory=list)
    exports: list[ExportArtifact] = Field(default_factory=list)
    generation_metadata: GenerationMetadata | None = None
    created_at: datetime = Field(default_factory=_default_timestamp)
    updated_at: datetime = Field(default_factory=_default_timestamp)

    @model_validator(mode="before")
    @classmethod
    def populate_editor_defaults(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value

        payload = dict(value)
        file_name = _clean_text(payload.get("file_name"))
        title = _clean_text(payload.get("title")) or Path(file_name).stem or "Research Paper"
        normalized_keywords = _normalize_string_list(payload.get("keywords"))

        generated_paper = _coerce_generated_paper(
            payload.get("generated_paper") or payload.get("generated_sections"),
            default_title=title,
            default_keywords=normalized_keywords,
            fallback_content=_clean_text(payload.get("content")),
        )
        edited_paper = _coerce_paper(
            payload.get("edited_paper") or payload.get("edited_sections"),
            default_title=title,
            default_keywords=normalized_keywords or (generated_paper.paper.keywords if generated_paper else []),
        )

        if not normalized_keywords and generated_paper is not None:
            normalized_keywords = list(generated_paper.paper.keywords)

        display_paper_text = _clean_text(payload.get("display_paper_text"))
        if not display_paper_text:
            if edited_paper is not None:
                display_paper_text = build_display_paper_text(edited_paper)
            elif generated_paper is not None:
                display_paper_text = generated_paper.formatted_text.strip()
            else:
                display_paper_text = _clean_text(payload.get("content")) or _clean_text(payload.get("extracted_text"))

        latex_ready = _clean_text(payload.get("latex_ready"))
        if not latex_ready:
            if generated_paper is not None:
                latex_ready = generated_paper.latex_ready
            else:
                latex_ready = display_paper_text

        content = _clean_text(payload.get("content")) or display_paper_text

        timestamp = payload.get("created_at") or payload.get("updated_at") or _default_timestamp()
        payload["title"] = title
        payload["owner_uid"] = _clean_text(payload.get("owner_uid"))
        payload["owner_email"] = _clean_text(payload.get("owner_email")).lower()
        payload["authors"] = _normalize_string_list(payload.get("authors"))
        payload["keywords"] = normalized_keywords
        payload["content"] = content
        payload["display_paper_text"] = display_paper_text
        payload["latex_ready"] = latex_ready
        payload["generated_paper"] = generated_paper
        payload["edited_paper"] = edited_paper
        payload["created_at"] = payload.get("created_at") or timestamp
        payload["updated_at"] = payload.get("updated_at") or payload["created_at"]
        return payload


class UploadResponse(BaseModel):
    project_id: str
    file_name: str
    extracted_text: str
    file_type: str
    file_size: int = Field(ge=0)
    extraction_time_ms: float = Field(ge=0)

    @classmethod
    def from_project(cls, project: ProjectRecord) -> "UploadResponse":
        return cls(
            project_id=project.id,
            file_name=project.file_name,
            extracted_text=project.extracted_text,
            file_type=project.file_type,
            file_size=project.file_size,
            extraction_time_ms=project.extraction_time_ms,
        )
