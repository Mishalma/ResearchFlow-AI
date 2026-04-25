from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from originality.schemas import OriginalitySpan

ValidationMode = Literal["ai_check", "final_report"]
ValidationConfidenceBand = Literal["unknown", "low", "medium", "high"]
ValidationRoutingDecision = Literal["pending", "accepted", "flagged"]
ValidationSectionRisk = Literal["low", "medium", "severe"]
ValidationSectionFlagType = Literal["ai", "plagiarism"]


class ValidationSectionFlag(BaseModel):
    section_id: str = Field(min_length=1)
    flag_type: ValidationSectionFlagType
    score: float = Field(ge=0.0)
    risk: ValidationSectionRisk
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self) -> "ValidationSectionFlag":
        self.section_id = self.section_id.strip()
        self.summary = self.summary.strip()
        return self


class ValidationSectionReport(BaseModel):
    section_name: str = Field(min_length=1)
    ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    plagiarism_score: float = Field(default=0.0, ge=0.0, le=100.0)
    status: str = Field(min_length=1)
    risk: ValidationSectionRisk
    summary: list[str] = Field(default_factory=list)
    spans: list[OriginalitySpan] = Field(default_factory=list)

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
    def normalize(self) -> "ValidationSectionReport":
        self.section_name = self.section_name.strip()
        self.status = self.status.strip()
        return self


class ValidationReport(BaseModel):
    ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    plagiarism_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence_band: ValidationConfidenceBand = "unknown"
    routing_decision: ValidationRoutingDecision = "pending"
    sections: list[ValidationSectionReport] = Field(default_factory=list)
    decision_summary: str = Field(min_length=1)
    initial_ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    initial_plagiarism_score: float | None = Field(default=None, ge=0.0, le=100.0)
    final_ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    final_plagiarism_score: float | None = Field(default=None, ge=0.0, le=100.0)
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "ValidationReport":
        self.decision_summary = self.decision_summary.strip()
        return self


class ValidationServiceArtifacts(BaseModel):
    extracted_text_uri: str | None = None
    previous_validation_report_uri: str | None = None


class ValidationServiceConfig(BaseModel):
    mode: ValidationMode = "ai_check"
    changed_sections_only: bool = False
    changed_section_ids: list[str] = Field(default_factory=list)

    @field_validator("changed_section_ids", mode="before")
    @classmethod
    def normalize_changed_section_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            section_id = str(item).strip()
            if not section_id:
                continue
            folded = section_id.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            normalized.append(section_id)
        return normalized


class ValidationServiceRequest(BaseModel):
    schema_version: str = "1.0.0"
    task_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=8)
    expected_status: Literal["VALIDATION_REQUESTED", "VALIDATING"] = "VALIDATION_REQUESTED"
    current_draft_uri: str = Field(min_length=1)
    artifacts: ValidationServiceArtifacts = Field(default_factory=ValidationServiceArtifacts)
    config: ValidationServiceConfig = Field(default_factory=ValidationServiceConfig)


class ValidationServiceOutput(BaseModel):
    mode: ValidationMode = "ai_check"
    ai_score: float | None = Field(default=None, ge=0.0, le=1.0)
    plagiarism_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence_band: ValidationConfidenceBand = "unknown"
    routing_decision: ValidationRoutingDecision = "pending"
    section_flags: list[ValidationSectionFlag] = Field(default_factory=list)
    validation_report_uri: str = Field(min_length=1)
    report: ValidationReport
    failure_reasons: list[str] = Field(default_factory=list)


class ValidationServiceResponse(BaseModel):
    job_id: str = Field(min_length=1)
    status: Literal["VALIDATING"] = "VALIDATING"
    stage: Literal["validation"] = "validation"
    output: ValidationServiceOutput
