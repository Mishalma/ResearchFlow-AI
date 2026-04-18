from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from models.generation import GeneratedPaper

REQUIRED_ORIGINALITY_SECTIONS = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)

CLASSIFICATION_LABELS = (
    "quoted_and_cited",
    "common_phrase",
    "boilerplate",
    "possible_self_overlap",
    "uncited_close_paraphrase",
    "likely_unattributed_copying",
    "manual_review_required",
)


class ProviderFinding(BaseModel):
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    matched_text: str = ""
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_source_title: str | None = None
    matched_source_url: str | None = None
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize(self) -> "ProviderFinding":
        if self.end_char < self.start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        self.matched_text = self.matched_text.strip()
        if self.matched_source_title is not None:
            cleaned = self.matched_source_title.strip()
            self.matched_source_title = cleaned or None
        if self.matched_source_url is not None:
            cleaned = self.matched_source_url.strip()
            self.matched_source_url = cleaned or None
        return self


class ProviderSectionScan(BaseModel):
    provider_name: str = Field(min_length=1)
    section_name: str = Field(min_length=1)
    originality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    spans: list[ProviderFinding] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize(self) -> "ProviderSectionScan":
        self.provider_name = self.provider_name.strip()
        self.section_name = self.section_name.strip()
        return self


class OriginalitySpan(BaseModel):
    section_name: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    matched_text: str = ""
    provider_name: str = Field(min_length=1)
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_source_title: str | None = None
    matched_source_url: str | None = None
    classification: str = Field(min_length=1)
    severity: float = Field(ge=0.0, le=1.0)
    remediation_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("remediation_actions", mode="before")
    @classmethod
    def normalize_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]

    @model_validator(mode="after")
    def normalize(self) -> "OriginalitySpan":
        if self.end_char < self.start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        self.section_name = self.section_name.strip()
        self.provider_name = self.provider_name.strip()
        self.matched_text = self.matched_text.strip()
        self.classification = self.classification.strip()
        if self.classification not in CLASSIFICATION_LABELS:
            raise ValueError(f"Unsupported originality classification '{self.classification}'")
        if self.matched_source_title is not None:
            cleaned = self.matched_source_title.strip()
            self.matched_source_title = cleaned or None
        if self.matched_source_url is not None:
            cleaned = self.matched_source_url.strip()
            self.matched_source_url = cleaned or None
        return self


class SectionOriginalityReport(BaseModel):
    section_name: str = Field(min_length=1)
    originality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    spans: list[OriginalitySpan] = Field(default_factory=list)
    status: str = Field(min_length=1)
    requires_manual_review: bool = False
    summary: list[str] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]

    @model_validator(mode="after")
    def normalize(self) -> "SectionOriginalityReport":
        self.section_name = self.section_name.strip()
        self.status = self.status.strip()
        return self


class OriginalityDecision(BaseModel):
    graph_action: str = Field(min_length=1)
    approved: bool
    reason_codes: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def normalize_reason_codes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]

    @model_validator(mode="after")
    def normalize(self) -> "OriginalityDecision":
        self.graph_action = self.graph_action.strip()
        self.summary = self.summary.strip()
        return self


class OriginalityPaperReport(BaseModel):
    sections: dict[str, SectionOriginalityReport] = Field(default_factory=dict)
    global_originality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    global_ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    decision: OriginalityDecision
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_required_sections(self) -> "OriginalityPaperReport":
        normalized = {str(name): report for name, report in self.sections.items()}
        for section_name in REQUIRED_ORIGINALITY_SECTIONS:
            normalized.setdefault(
                section_name,
                SectionOriginalityReport(
                    section_name=section_name,
                    status="clean",
                ),
            )
        self.sections = normalized
        return self


class OriginalityAgentError(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    trace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class OriginalityAgentResult(BaseModel):
    approved_snapshot: GeneratedPaper | None = None
    originality_report: OriginalityPaperReport | None = None
    error: OriginalityAgentError | None = None
    trace_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "OriginalityAgentResult":
        if self.approved_snapshot is None and self.originality_report is None and self.error is None:
            raise ValueError("result must include an approved_snapshot, originality_report, or error")
        return self
