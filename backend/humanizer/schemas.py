from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from models.generation import GeneratedPaper

REQUIRED_HUMANIZER_SECTIONS = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)


class DetectedPattern(BaseModel):
    pattern_type: str = Field(min_length=1)
    severity: float = Field(ge=0.0, le=1.0)
    location: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


class ParagraphHumanizationReport(BaseModel):
    paragraph_index: int = Field(ge=0)
    original_perplexity: float = Field(ge=0.0)
    final_perplexity: float = Field(ge=0.0)
    cadence_score_before: float = Field(ge=0.0, le=1.0)
    cadence_score_after: float = Field(ge=0.0, le=1.0)
    ai_pattern_score_before: float = Field(ge=0.0, le=1.0)
    ai_pattern_score_after: float = Field(ge=0.0, le=1.0)
    rewrites_applied: list[str] = Field(default_factory=list)

    @field_validator("rewrites_applied", mode="before")
    @classmethod
    def normalize_rewrites(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


class SectionHumanizationReport(BaseModel):
    section_name: str = Field(min_length=1)
    original_text: str = ""
    final_text: str = ""
    original_perplexity: float = Field(ge=0.0)
    final_perplexity: float = Field(ge=0.0)
    detected_patterns: list[DetectedPattern] = Field(default_factory=list)
    paragraph_reports: list[ParagraphHumanizationReport] = Field(default_factory=list)
    rewrite_iterations: int = Field(ge=0)
    passed_threshold: bool
    needs_graph_retry: bool = False
    needs_writer_loopback: bool = False

    @model_validator(mode="after")
    def normalize(self) -> "SectionHumanizationReport":
        self.section_name = self.section_name.strip()
        self.original_text = self.original_text.strip()
        self.final_text = self.final_text.strip()
        return self


class HumanizedSection(BaseModel):
    section_name: str = Field(min_length=1)
    text: str = ""
    diff_summary: list[str] = Field(default_factory=list)
    report: SectionHumanizationReport

    @field_validator("diff_summary", mode="before")
    @classmethod
    def normalize_diff_summary(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]

    @model_validator(mode="after")
    def normalize(self) -> "HumanizedSection":
        self.section_name = self.section_name.strip()
        self.text = self.text.strip()
        return self


class HumanizedPaperDraft(BaseModel):
    sections: dict[str, HumanizedSection] = Field(default_factory=dict)
    global_ai_pattern_score_before: float = Field(ge=0.0, le=1.0)
    global_ai_pattern_score_after: float = Field(ge=0.0, le=1.0)
    global_perplexity_before: float = Field(ge=0.0)
    global_perplexity_after: float = Field(ge=0.0)
    passed_threshold: bool
    graph_action: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_required_sections(self) -> "HumanizedPaperDraft":
        normalized = {str(name): value for name, value in self.sections.items()}
        for section_name in REQUIRED_HUMANIZER_SECTIONS:
            normalized.setdefault(
                section_name,
                HumanizedSection(
                    section_name=section_name,
                    text="",
                    report=SectionHumanizationReport(
                        section_name=section_name,
                        original_text="",
                        final_text="",
                        original_perplexity=0.0,
                        final_perplexity=0.0,
                        rewrite_iterations=0,
                        passed_threshold=False,
                        needs_graph_retry=False,
                        needs_writer_loopback=False,
                    ),
                ),
            )
        self.sections = normalized
        self.graph_action = self.graph_action.strip()
        return self


class HumanizerAgentError(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    trace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class HumanizerAgentResult(BaseModel):
    humanized_draft: HumanizedPaperDraft | None = None
    paper_snapshot: GeneratedPaper | None = None
    error: HumanizerAgentError | None = None
    trace_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "HumanizerAgentResult":
        if self.humanized_draft is None and self.error is None:
            raise ValueError("result must include a humanized_draft or an error")
        return self
