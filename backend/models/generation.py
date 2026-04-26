from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from figure_table.models import FigureSpec, FigureTableOutput, RenderedFigure

GenerationProvider = Literal["vertex_ai"]
FigureTableStageStatus = Literal["succeeded", "partial", "failed", "skipped"]
IEEE_SECTION_KEYS = (
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)


class IEEESectionMap(BaseModel):
    introduction: str = Field(min_length=1)
    related_work: str = Field(min_length=1)
    methodology: str = Field(min_length=1)
    results: str = Field(min_length=1)
    discussion: str = Field(min_length=1)
    limitations: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self) -> "IEEESectionMap":
        self.introduction = self.introduction.strip()
        self.related_work = self.related_work.strip()
        self.methodology = self.methodology.strip()
        self.results = self.results.strip()
        self.discussion = self.discussion.strip()
        self.limitations = self.limitations.strip()
        self.conclusion = self.conclusion.strip()
        return self


class ResearchPaperSchema(BaseModel):
    title: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    sections: IEEESectionMap
    references: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "ResearchPaperSchema":
        self.title = self.title.strip()
        self.abstract = self.abstract.strip()
        self.keywords = [keyword.strip() for keyword in self.keywords if keyword.strip()]
        self.references = [reference.strip() for reference in self.references if reference.strip()]
        return self


class CitationSource(BaseModel):
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1900, le=2100)
    source: str = Field(min_length=1)
    query: str = Field(min_length=1)
    ieee_reference: str = Field(min_length=1)


class GeneratedPaper(BaseModel):
    paper: ResearchPaperSchema
    formatted_text: str = Field(min_length=1)
    latex_ready: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self) -> "GeneratedPaper":
        self.formatted_text = self.formatted_text.strip()
        self.latex_ready = self.latex_ready.strip()
        return self


class AgentTiming(BaseModel):
    agent: str
    duration_ms: float = Field(ge=0)


class GenerationMetadata(BaseModel):
    provider: GenerationProvider = "vertex_ai"
    model: str
    generation_time_ms: float = Field(ge=0)
    source_text_length: int = Field(ge=0)
    trace_id: str
    agent_timings: list[AgentTiming] = Field(default_factory=list)
    mcp_tools_used: list[str] = Field(default_factory=list)
    validation_events: list[str] = Field(default_factory=list)
    structuring_global_confidence: float | None = Field(default=None, ge=0, le=1)
    structuring_section_confidences: dict[str, float] = Field(default_factory=dict)
    structuring_evidence_summary: dict[str, int] = Field(default_factory=dict)
    writing_global_confidence: float | None = Field(default=None, ge=0, le=1)
    writing_section_confidences: dict[str, float] = Field(default_factory=dict)
    writing_annotation_summary: dict[str, int] = Field(default_factory=dict)
    citation_match_count: int | None = Field(default=None, ge=0)
    citation_bibliography_count: int | None = Field(default=None, ge=0)
    citation_provider_summary: dict[str, int] = Field(default_factory=dict)
    figure_table_figure_count: int | None = Field(default=None, ge=0)
    figure_table_table_count: int | None = Field(default=None, ge=0)
    formatting_compile_success: bool | None = None
    formatting_retry_recommended: bool | None = None
    formatting_diagnostic_summary: dict[str, int] = Field(default_factory=dict)
    humanizer_ai_pattern_score_before: float | None = Field(default=None, ge=0, le=1)
    humanizer_ai_pattern_score_after: float | None = Field(default=None, ge=0, le=1)
    humanizer_perplexity_before: float | None = Field(default=None, ge=0)
    humanizer_perplexity_after: float | None = Field(default=None, ge=0)
    humanizer_iterations: int | None = Field(default=None, ge=0)
    humanizer_graph_action: str | None = None
    originality_provider_used: str | None = None
    originality_global_score: float | None = Field(default=None, ge=0, le=1)
    originality_global_ai_score: float | None = Field(default=None, ge=0, le=1)
    originality_section_status_counts: dict[str, int] = Field(default_factory=dict)
    originality_decision: str | None = None
    originality_flagged_span_count: int | None = Field(default=None, ge=0)

    @field_validator("structuring_section_confidences")
    @classmethod
    def validate_structuring_section_confidences(
        cls,
        value: dict[str, float],
    ) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, score in value.items():
            bounded_score = float(score)
            if not 0.0 <= bounded_score <= 1.0:
                raise ValueError(f"structuring confidence for '{key}' must be between 0 and 1")
            normalized[str(key)] = bounded_score
        return normalized

    @field_validator("structuring_evidence_summary")
    @classmethod
    def validate_structuring_evidence_summary(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"structuring evidence count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized

    @field_validator("writing_section_confidences")
    @classmethod
    def validate_writing_section_confidences(
        cls,
        value: dict[str, float],
    ) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, score in value.items():
            bounded_score = float(score)
            if not 0.0 <= bounded_score <= 1.0:
                raise ValueError(f"writing confidence for '{key}' must be between 0 and 1")
            normalized[str(key)] = bounded_score
        return normalized

    @field_validator("writing_annotation_summary")
    @classmethod
    def validate_writing_annotation_summary(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"writing annotation count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized

    @field_validator("citation_provider_summary")
    @classmethod
    def validate_citation_provider_summary(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"citation provider count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized

    @field_validator("formatting_diagnostic_summary")
    @classmethod
    def validate_formatting_diagnostic_summary(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"formatting diagnostic count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized

    @field_validator("originality_section_status_counts")
    @classmethod
    def validate_originality_section_status_counts(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"originality status count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized


class StructuringAgentOutput(ResearchPaperSchema):
    structured_draft: dict[str, Any] | None = None
    global_confidence: float = Field(default=0.0, ge=0, le=1)
    section_confidences: dict[str, float] = Field(default_factory=dict)
    evidence_summary: dict[str, int] = Field(default_factory=dict)
    trace_id: str | None = None
    error: dict[str, Any] | None = None

    @field_validator("section_confidences")
    @classmethod
    def validate_section_confidences(cls, value: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, score in value.items():
            bounded_score = float(score)
            if not 0.0 <= bounded_score <= 1.0:
                raise ValueError(f"section confidence for '{key}' must be between 0 and 1")
            normalized[str(key)] = bounded_score
        return normalized

    @field_validator("evidence_summary")
    @classmethod
    def validate_evidence_summary(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"evidence count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized


class WritingAgentOutput(ResearchPaperSchema):
    written_draft: dict[str, Any] | None = None
    global_confidence: float = Field(default=0.0, ge=0, le=1)
    section_confidences: dict[str, float] = Field(default_factory=dict)
    annotation_summary: dict[str, int] = Field(default_factory=dict)
    trace_id: str | None = None
    error: dict[str, Any] | None = None

    @field_validator("section_confidences")
    @classmethod
    def validate_section_confidences(cls, value: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, score in value.items():
            bounded_score = float(score)
            if not 0.0 <= bounded_score <= 1.0:
                raise ValueError(f"writing section confidence for '{key}' must be between 0 and 1")
            normalized[str(key)] = bounded_score
        return normalized

    @field_validator("annotation_summary")
    @classmethod
    def validate_annotation_summary(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"writing annotation count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized


class CitationAgentOutput(ResearchPaperSchema):
    citation_draft: dict[str, Any] | None = None
    matched_claim_count: int = Field(default=0, ge=0)
    bibliography_count: int = Field(default=0, ge=0)
    provider_summary: dict[str, int] = Field(default_factory=dict)
    trace_id: str | None = None
    error: dict[str, Any] | None = None

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


class FormattingAgentOutput(BaseModel):
    paper: ResearchPaperSchema
    formatted_text: str = Field(min_length=1)
    latex_ready: str = Field(min_length=1)
    formatted_paper: dict[str, Any] | None = None
    compile_success: bool | None = None
    retry_recommended: bool | None = None
    diagnostic_summary: dict[str, int] = Field(default_factory=dict)
    trace_id: str | None = None
    error: dict[str, Any] | None = None

    @field_validator("diagnostic_summary")
    @classmethod
    def validate_diagnostic_summary(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"formatting diagnostic count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized

    @model_validator(mode="after")
    def normalize(self) -> "FormattingAgentOutput":
        self.formatted_text = self.formatted_text.strip()
        self.latex_ready = self.latex_ready.strip()
        return self


class HumanizerAgentOutput(BaseModel):
    paper: ResearchPaperSchema
    formatted_text: str = Field(min_length=1)
    latex_ready: str = Field(min_length=1)
    humanized_draft: dict[str, Any] | None = None
    ai_pattern_score_before: float | None = Field(default=None, ge=0, le=1)
    ai_pattern_score_after: float | None = Field(default=None, ge=0, le=1)
    perplexity_before: float | None = Field(default=None, ge=0)
    perplexity_after: float | None = Field(default=None, ge=0)
    iteration_count: int = Field(default=0, ge=0)
    graph_action: str | None = None
    trace_id: str | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize(self) -> "HumanizerAgentOutput":
        self.formatted_text = self.formatted_text.strip()
        self.latex_ready = self.latex_ready.strip()
        if self.graph_action is not None:
            self.graph_action = self.graph_action.strip() or None
        return self


class FigureTableAgentOutput(BaseModel):
    figures: list[RenderedFigure] | None = None
    tables: list[RenderedFigure] | None = None
    enriched_draft: str = ""
    figure_count: int = Field(default=0, ge=0)
    table_count: int = Field(default=0, ge=0)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
    enriched_written_draft: dict[str, Any] | None = None
    status: FigureTableStageStatus = "succeeded"
    error: str | None = None


class OriginalityAgentOutput(BaseModel):
    approved_snapshot: GeneratedPaper | None = None
    originality_report: dict[str, Any] | None = None
    provider_used: str | None = None
    global_originality_score: float | None = Field(default=None, ge=0, le=1)
    global_ai_score: float | None = Field(default=None, ge=0, le=1)
    section_status_counts: dict[str, int] = Field(default_factory=dict)
    decision_graph_action: str | None = None
    approved: bool = False
    trace_id: str | None = None
    error: dict[str, Any] | None = None

    @field_validator("section_status_counts")
    @classmethod
    def validate_section_status_counts(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_count = int(count)
            if normalized_count < 0:
                raise ValueError(f"section status count for '{key}' cannot be negative")
            normalized[str(key)] = normalized_count
        return normalized

    @model_validator(mode="after")
    def validate_payload(self) -> "OriginalityAgentOutput":
        if self.approved_snapshot is None and self.originality_report is None and self.error is None:
            raise ValueError("originality output must include an approved_snapshot, originality_report, or error")
        if self.provider_used is not None:
            self.provider_used = self.provider_used.strip() or None
        if self.decision_graph_action is not None:
            self.decision_graph_action = self.decision_graph_action.strip() or None
        return self


class PipelineResult(BaseModel):
    generated_paper: GeneratedPaper
    metadata: GenerationMetadata
    generated_figures: list[RenderedFigure] | None = None
    generated_tables: list[RenderedFigure] | None = None
    figure_table_status: FigureTableStageStatus | None = None
    figure_table_error: str | None = None
    remediation_context: dict[str, Any] = Field(default_factory=dict)


class GenerationServiceRequest(BaseModel):
    job_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8)
    provider_override: str | None = None
    model_override: str | None = None


class GenerationServiceResponse(BaseModel):
    job_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    generated_paper: GeneratedPaper
    metadata: GenerationMetadata
    generated_figures: list[RenderedFigure] | None = None
    generated_tables: list[RenderedFigure] | None = None
    figure_table_status: FigureTableStageStatus | None = None
    figure_table_error: str | None = None
    remediation_context: dict[str, Any] = Field(default_factory=dict)
    boundary: Literal["formatting_complete"] = "formatting_complete"


class GenerateRequest(BaseModel):
    project_id: str = Field(min_length=1)


class GenerateResponse(BaseModel):
    project_id: str
    generated_paper: GeneratedPaper
    provider: GenerationProvider
    model: str
    generation_time_ms: float = Field(ge=0)
    trace_id: str
    agent_timings: list[AgentTiming] = Field(default_factory=list)

    @classmethod
    def from_generation(
        cls,
        project_id: str,
        generated_paper: GeneratedPaper,
        metadata: GenerationMetadata,
    ) -> "GenerateResponse":
        return cls(
            project_id=project_id,
            generated_paper=generated_paper,
            provider=metadata.provider,
            model=metadata.model,
            generation_time_ms=metadata.generation_time_ms,
            trace_id=metadata.trace_id,
            agent_timings=metadata.agent_timings,
        )
