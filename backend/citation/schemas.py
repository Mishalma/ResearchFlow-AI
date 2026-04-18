from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from models.generation import ResearchPaperSchema

REQUIRED_CITATION_SECTIONS = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)


class ClaimQuery(BaseModel):
    claim_id: str = Field(min_length=1)
    section_name: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_class: str = Field(default="context", min_length=1)
    source_span_ids: list[str] = Field(default_factory=list)
    source_spans: list[dict[str, Any]] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    provider_route: list[str] = Field(default_factory=list)
    requires_external_citation: bool = True
    notes: list[str] = Field(default_factory=list)

    @field_validator("source_span_ids", "search_queries", "provider_route", "notes", mode="before")
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
    def normalize(self) -> "ClaimQuery":
        self.claim_text = self.claim_text.strip()
        self.claim_type = self.claim_type.strip()
        self.section_name = self.section_name.strip()
        self.evidence_class = self.evidence_class.strip()
        return self


class CandidateScores(BaseModel):
    lexical_score: float = Field(default=0.0, ge=0, le=1)
    semantic_score: float = Field(default=0.0, ge=0, le=1)
    cross_encoder_score: float | None = Field(default=None, ge=0, le=1)
    provider_score: float = Field(default=0.0, ge=0, le=1)
    doi_score: float = Field(default=0.0, ge=0, le=1)
    final_score: float = Field(default=0.0, ge=0, le=1)


class ProviderCandidate(BaseModel):
    candidate_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1800, le=2100)
    venue: str | None = None
    abstract: str | None = None
    doi: str | None = None
    url: str | None = None
    source_query: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    citation_count: int | None = Field(default=None, ge=0)
    external_ids: dict[str, str] = Field(default_factory=dict)
    provider_provenance: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    scores: CandidateScores | None = None
    doi_status: str | None = None
    ieee_reference: str | None = None

    @field_validator("authors", "publication_types", "provider_provenance", mode="before")
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
    def normalize(self) -> "ProviderCandidate":
        self.title = self.title.strip()
        self.provider = self.provider.strip()
        self.provider_id = self.provider_id.strip()
        self.candidate_id = self.candidate_id.strip()
        if self.venue is not None:
            cleaned = self.venue.strip()
            self.venue = cleaned or None
        if self.abstract is not None:
            cleaned = self.abstract.strip()
            self.abstract = cleaned or None
        if self.doi is not None:
            cleaned = self.doi.strip()
            self.doi = cleaned or None
        if self.url is not None:
            cleaned = self.url.strip()
            self.url = cleaned or None
        if self.provider not in self.provider_provenance:
            self.provider_provenance.append(self.provider)
        return self


class BibliographyEntry(BaseModel):
    entry_id: str = Field(min_length=1)
    citation_number: int = Field(ge=1)
    title: str = Field(min_length=1)
    ieee_reference: str = Field(min_length=1)
    doi: str | None = None
    providers: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1800, le=2100)
    venue: str | None = None
    url: str | None = None


class MatchedCitation(BaseModel):
    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    selected_candidates: list[ProviderCandidate] = Field(default_factory=list)
    candidate_pool: list[ProviderCandidate] = Field(default_factory=list)
    bibliography_entry_ids: list[str] = Field(default_factory=list)
    status: str = Field(default="matched", min_length=1)
    notes: list[str] = Field(default_factory=list)


class SectionCitationResult(BaseModel):
    section_name: str = Field(min_length=1)
    claims: list[ClaimQuery] = Field(default_factory=list)
    matches: list[MatchedCitation] = Field(default_factory=list)
    provider_summary: dict[str, int] = Field(default_factory=dict)

    @field_validator("provider_summary")
    @classmethod
    def validate_provider_summary(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"provider count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized


class CitationDraft(BaseModel):
    title: str = Field(min_length=1)
    sections: dict[str, SectionCitationResult] = Field(default_factory=dict)
    bibliography: list[BibliographyEntry] = Field(default_factory=list)
    matched_claim_count: int = Field(default=0, ge=0)
    bibliography_count: int = Field(default=0, ge=0)
    provider_summary: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_required_sections(self) -> "CitationDraft":
        normalized_sections = {str(name): section for name, section in self.sections.items()}
        for section_name in REQUIRED_CITATION_SECTIONS:
            normalized_sections.setdefault(
                section_name,
                SectionCitationResult(section_name=section_name),
            )
        self.sections = normalized_sections
        self.matched_claim_count = sum(
            1
            for section in self.sections.values()
            for match in section.matches
            if match.selected_candidates
        )
        self.bibliography_count = len(self.bibliography)
        return self


class CitationAgentError(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    trace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CitationAgentResult(BaseModel):
    citation_draft: CitationDraft | None = None
    paper_snapshot: ResearchPaperSchema | None = None
    error: CitationAgentError | None = None
    trace_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "CitationAgentResult":
        if self.citation_draft is None and self.error is None:
            raise ValueError("result must include a citation_draft or an error")
        return self
