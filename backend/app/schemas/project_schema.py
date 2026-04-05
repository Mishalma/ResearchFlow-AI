from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.generation import GeneratedPaper, GenerationMetadata, PaperSections
from app.models.project import ExportArtifact, FigureRecord, ProjectRecord


class SectionUpdate(BaseModel):
    abstract: str | None = Field(default=None, min_length=1)
    introduction: str | None = Field(default=None, min_length=1)
    methodology: str | None = Field(default=None, min_length=1)
    conclusion: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_at_least_one_section(self) -> "SectionUpdate":
        if not any(
            value is not None
            for value in (
                self.abstract,
                self.introduction,
                self.methodology,
                self.conclusion,
            )
        ):
            raise ValueError("At least one section must be provided.")

        return self


class SaveRequest(BaseModel):
    project_id: str = Field(min_length=1)
    sections: SectionUpdate


class SaveResponse(BaseModel):
    success: bool = True
    project_id: str
    sections: PaperSections
    updated_at: datetime


class ProjectResponse(BaseModel):
    id: str
    file_name: str
    file_path: str
    extracted_text: str
    file_type: str
    file_size: int = Field(ge=0)
    extraction_time_ms: float = Field(ge=0)
    generated_sections: PaperSections | None = None
    edited_sections: PaperSections | None = None
    sections: PaperSections | None = None
    figures: list[FigureRecord] = Field(default_factory=list)
    exports: list[ExportArtifact] = Field(default_factory=list)
    generated_paper: GeneratedPaper | None = None
    generation_metadata: GenerationMetadata | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_project(cls, project: ProjectRecord) -> "ProjectResponse":
        return cls(
            id=project.id,
            file_name=project.file_name,
            file_path=project.file_path,
            extracted_text=project.extracted_text,
            file_type=project.file_type,
            file_size=project.file_size,
            extraction_time_ms=project.extraction_time_ms,
            generated_sections=project.generated_sections,
            edited_sections=project.edited_sections,
            sections=project.edited_sections or project.generated_sections,
            figures=project.figures,
            exports=project.exports,
            generated_paper=project.generated_paper,
            generation_metadata=project.generation_metadata,
            updated_at=project.updated_at,
        )
