from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from models.generation import ResearchPaperSchema

REQUIRED_STRUCTURING_SECTIONS = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)


class TextChunk(BaseModel):
    """A deterministic source chunk with offsets into the normalized input text."""

    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> "TextChunk":
        if self.start_char > self.end_char:
            raise ValueError("chunk start_char must be <= end_char")
        self.text = self.text.strip()
        return self


class SourceSpan(BaseModel):
    chunk_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    quote: str | None = None
    relevance_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> "SourceSpan":
        if self.start_char > self.end_char:
            raise ValueError("source span start_char must be <= end_char")
        if self.quote is not None:
            cleaned = self.quote.strip()
            self.quote = cleaned or None
        return self


class EvidenceNote(BaseModel):
    section_name: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    note: str = ""
    direct_evidence: list[str] = Field(default_factory=list)
    inferred_synthesis: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0, le=1)

    @field_validator(
        "direct_evidence",
        "inferred_synthesis",
        "missing_information",
        mode="before",
    )
    @classmethod
    def normalize_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


class SectionSkeleton(BaseModel):
    section_name: str = Field(min_length=1)
    draft: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    key_points: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    direct_evidence: list[str] = Field(default_factory=list)
    inferred_synthesis: list[str] = Field(default_factory=list)

    @field_validator(
        "key_points",
        "missing_evidence",
        "direct_evidence",
        "inferred_synthesis",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]

    @model_validator(mode="after")
    def normalize_draft(self) -> "SectionSkeleton":
        self.draft = self.draft.strip()
        return self


class StructuredPaperDraft(BaseModel):
    title_candidates: list[str] = Field(default_factory=list)
    sections: dict[str, SectionSkeleton] = Field(default_factory=dict)
    evidence_notes: dict[str, list[EvidenceNote]] = Field(default_factory=dict)
    global_confidence: float = Field(default=0.0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title_candidates", mode="before")
    @classmethod
    def normalize_title_candidates(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        deduplicated: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = str(candidate).strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(cleaned)
        return deduplicated

    @model_validator(mode="after")
    def ensure_all_sections(self) -> "StructuredPaperDraft":
        normalized_sections = {str(name): section for name, section in self.sections.items()}
        for section_name in REQUIRED_STRUCTURING_SECTIONS:
            normalized_sections.setdefault(
                section_name,
                SectionSkeleton(section_name=section_name),
            )
            self.evidence_notes.setdefault(section_name, [])
        self.sections = normalized_sections
        return self


class StructuringAgentError(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    recoverable: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class StructuringAgentResult(BaseModel):
    structured_draft: StructuredPaperDraft | None = None
    paper_snapshot: ResearchPaperSchema | None = None
    error: StructuringAgentError | None = None
    trace_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_payload(self) -> "StructuringAgentResult":
        if self.structured_draft is None and self.error is None:
            raise ValueError("result must include a structured_draft or an error")
        return self
