from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.generation import ResearchPaperSchema
from app.models.project import FigureRecord, ProjectRecord


class SaveProjectRequest(BaseModel):
    project_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    content: str | None = None
    paper: ResearchPaperSchema | None = None

    @model_validator(mode="after")
    def validate_text_fields(self) -> "SaveProjectRequest":
        self.title = self.title.strip()
        self.authors = [author.strip() for author in self.authors if author.strip()]
        self.keywords = [keyword.strip() for keyword in self.keywords if keyword.strip()]

        if self.content is not None:
            self.content = self.content.strip()

        if not self.title:
            raise ValueError("Project title is required.")

        has_content = bool(self.content)
        has_paper = self.paper is not None
        if not has_content and not has_paper:
            raise ValueError("Project content is required.")

        return self


class ProjectSummaryResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_project(cls, project: ProjectRecord) -> "ProjectSummaryResponse":
        return cls(
            id=project.id,
            title=project.title,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectResponse(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    display_paper_text: str = Field(default="")
    paper: ResearchPaperSchema | None = None
    figures: list[FigureRecord] = Field(default_factory=list)
    generated_figures: list[dict] = Field(default_factory=list)
    generated_tables: list[dict] = Field(default_factory=list)

    @classmethod
    def from_project(cls, project: ProjectRecord) -> "ProjectResponse":
        effective_paper = project.edited_paper or (
            project.generated_paper.paper if project.generated_paper else None
        )
        return cls(
            id=project.id,
            title=project.title,
            authors=project.authors,
            display_paper_text=project.display_paper_text or project.content,
            paper=effective_paper,
            figures=project.figures,
            generated_figures=project.generated_figures,
            generated_tables=project.generated_tables,
        )


class SaveProjectResponse(BaseModel):
    success: bool = True
    project: ProjectResponse
