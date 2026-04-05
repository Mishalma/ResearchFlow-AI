from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GenerationProvider = Literal["vertex_ai"]


class PaperSections(BaseModel):
    abstract: str = Field(min_length=1)
    introduction: str = Field(min_length=1)
    methodology: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)


class CitationSource(BaseModel):
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1900, le=2100)
    source: str = Field(min_length=1)
    query: str = Field(min_length=1)
    ieee_reference: str = Field(min_length=1)


class GeneratedPaper(PaperSections):
    references: list[str] = Field(default_factory=list)
    citation_sources: list[CitationSource] = Field(default_factory=list)
    formatted_paper: str = Field(min_length=1)


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


class StructuringAgentOutput(PaperSections):
    pass


class WritingAgentOutput(PaperSections):
    pass


class CitationAgentOutput(PaperSections):
    references: list[str] = Field(default_factory=list)
    citation_sources: list[CitationSource] = Field(default_factory=list)


class FormattingAgentOutput(GeneratedPaper):
    pass


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
