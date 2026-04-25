from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from models.job import FixSummary, WorkflowArtifactPointer

FixMode = Literal["ai_style"]
FixRisk = Literal["medium", "severe"]
FixStatus = Literal["not_needed", "applied", "failed", "no_change"]


class FixSectionTarget(BaseModel):
    section_id: str = Field(min_length=1)
    flag_type: Literal["ai"] = "ai"
    risk: FixRisk = "medium"
    score: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self) -> "FixSectionTarget":
        self.section_id = self.section_id.strip()
        self.summary = self.summary.strip()
        return self


class FixServiceRequest(BaseModel):
    schema_version: str = "1.0.0"
    task_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=8)
    current_draft_uri: str = Field(min_length=1)
    validation_report_uri: str = Field(min_length=1)
    iteration: int = Field(default=1, ge=1, le=5)
    mode: FixMode = "ai_style"
    targets: list[FixSectionTarget] = Field(default_factory=list)

    @field_validator("targets", mode="before")
    @classmethod
    def normalize_targets(cls, value: object) -> list[FixSectionTarget]:
        if value is None:
            return []
        return list(value)


class FixServiceOutput(BaseModel):
    mode: FixMode = "ai_style"
    updated_draft_uri: str = Field(min_length=1)
    draft_artifact: WorkflowArtifactPointer | None = None
    changed_sections: list[str] = Field(default_factory=list)
    changed: bool = False
    rewriter_mode: str | None = None
    fix_status: FixStatus = "not_needed"
    fallback_reason: str | None = None
    fix_summary: FixSummary

    @field_validator("changed_sections", mode="before")
    @classmethod
    def normalize_changed_sections(cls, value: object) -> list[str]:
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


class FixServiceResponse(BaseModel):
    job_id: str = Field(min_length=1)
    status: Literal["FIXING"] = "FIXING"
    stage: Literal["fix"] = "fix"
    output: FixServiceOutput
