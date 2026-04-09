from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

GenerationProvider = Literal["vertex_ai"]


class IEEESectionMap(BaseModel):
    introduction: str = Field(min_length=1)
    related_work: str = Field(min_length=1)
    methodology: str = Field(min_length=1)
    results: str = Field(min_length=1)
    discussion: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self) -> "IEEESectionMap":
        self.introduction = self.introduction.strip()
        self.related_work = self.related_work.strip()
        self.methodology = self.methodology.strip()
        self.results = self.results.strip()
        self.discussion = self.discussion.strip()
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


class StructuringAgentOutput(ResearchPaperSchema):
    pass


class WritingAgentOutput(ResearchPaperSchema):
    pass


class CitationAgentOutput(ResearchPaperSchema):
    pass


class FormattingAgentOutput(BaseModel):
    paper: ResearchPaperSchema
    formatted_text: str = Field(min_length=1)
    latex_ready: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self) -> "FormattingAgentOutput":
        self.formatted_text = self.formatted_text.strip()
        self.latex_ready = self.latex_ready.strip()
        return self


class PipelineResult(BaseModel):
    generated_paper: GeneratedPaper
    metadata: GenerationMetadata


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
