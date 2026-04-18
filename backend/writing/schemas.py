from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from models.generation import IEEESectionMap, ResearchPaperSchema

REQUIRED_WRITING_SECTIONS = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)

BODY_WRITING_SECTIONS = tuple(section for section in REQUIRED_WRITING_SECTIONS if section != "abstract")


class WrittenClaim(BaseModel):
    text: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    source_span_ids: list[str] = Field(default_factory=list)
    is_inferred: bool = False
    is_hedged: bool = False

    @model_validator(mode="after")
    def normalize(self) -> "WrittenClaim":
        self.text = self.text.strip()
        self.claim_type = self.claim_type.strip()
        self.source_span_ids = [span_id.strip() for span_id in self.source_span_ids if span_id.strip()]
        return self


class WrittenSection(BaseModel):
    section_name: str = Field(min_length=1)
    text: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    claims: list[WrittenClaim] = Field(default_factory=list)
    evidence_backed_sentences: list[str] = Field(default_factory=list)
    inferred_sentences: list[str] = Field(default_factory=list)
    hedged_sentences: list[str] = Field(default_factory=list)
    unsupported_sentences: list[str] = Field(default_factory=list)
    used_source_spans: list[dict[str, Any]] = Field(default_factory=list)
    revision_notes: list[str] = Field(default_factory=list)

    @field_validator(
        "evidence_backed_sentences",
        "inferred_sentences",
        "hedged_sentences",
        "unsupported_sentences",
        "revision_notes",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]

    @model_validator(mode="after")
    def normalize(self) -> "WrittenSection":
        self.section_name = self.section_name.strip()
        self.text = self.text.strip()
        return self


class WrittenPaperDraft(BaseModel):
    title: str = Field(min_length=1)
    abstract: WrittenSection
    sections: dict[str, WrittenSection] = Field(default_factory=dict)
    global_confidence: float = Field(default=0.0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_required_sections(self) -> "WrittenPaperDraft":
        self.title = self.title.strip()
        if self.abstract.section_name != "abstract":
            self.abstract.section_name = "abstract"

        normalized_sections = {str(name): section for name, section in self.sections.items()}
        for section_name in BODY_WRITING_SECTIONS:
            normalized_sections.setdefault(
                section_name,
                WrittenSection(section_name=section_name, text=""),
            )
        self.sections = normalized_sections
        return self


class WritingAgentError(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    trace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WritingAgentResult(BaseModel):
    written_draft: WrittenPaperDraft | None = None
    paper_snapshot: ResearchPaperSchema | None = None
    error: WritingAgentError | None = None
    trace_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "WritingAgentResult":
        if self.written_draft is None and self.error is None:
            raise ValueError("result must include a written_draft or an error")
        return self


def build_paper_snapshot(
    *,
    title: str,
    abstract: str,
    keywords: list[str],
    sections: dict[str, WrittenSection],
    references: list[str] | None = None,
) -> ResearchPaperSchema:
    return ResearchPaperSchema(
        title=title,
        abstract=abstract,
        keywords=keywords,
        sections=IEEESectionMap(
            introduction=sections["introduction"].text or "Introduction requires author review.",
            related_work=sections["related_work"].text or "Related work requires author review.",
            methodology=sections["methodology"].text or "Methodology requires author review.",
            results=sections["results"].text or "Results require author review.",
            discussion=sections["discussion"].text or "Discussion requires author review.",
            limitations=sections["limitations"].text or "Limitations require author review.",
            conclusion=sections["conclusion"].text or "Conclusion requires author review.",
        ),
        references=list(references or []),
    )
