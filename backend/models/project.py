from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from pydantic import BaseModel, Field

from models.generation import GeneratedPaper, GenerationMetadata, PaperSections

FigureSection = Literal["abstract", "introduction", "methodology", "conclusion"]
ExportFormat = Literal["pdf", "docx", "latex"]


class FigureRecord(BaseModel):
    id: str
    original_file_name: str
    stored_file_name: str
    file_size: int = Field(ge=0)
    content_type: str
    path: str
    public_url: str
    caption: str = Field(min_length=1)
    section: FigureSection
    uploaded_at: datetime


class ExportArtifact(BaseModel):
    id: str
    format: ExportFormat
    file_name: str
    path: str
    download_url: str
    created_at: datetime


class ProjectRecord(BaseModel):
    id: str
    file_name: str
    file_path: str
    extracted_text: str
    file_type: str
    file_size: int = Field(ge=0)
    extraction_time_ms: float = Field(ge=0)
    generated_sections: PaperSections | None = None
    edited_sections: PaperSections | None = None
    figures: list[FigureRecord] = Field(default_factory=list)
    exports: list[ExportArtifact] = Field(default_factory=list)
    generated_paper: GeneratedPaper | None = None
    generation_metadata: GenerationMetadata | None = None
    updated_at: datetime | None = None


class UploadResponse(BaseModel):
    project_id: str
    file_name: str
    extracted_text: str
    file_type: str
    file_size: int = Field(ge=0)
    extraction_time_ms: float = Field(ge=0)

    @classmethod
    def from_project(cls, project: ProjectRecord) -> "UploadResponse":
        return cls(
            project_id=project.id,
            file_name=project.file_name,
            extracted_text=project.extracted_text,
            file_type=project.file_type,
            file_size=project.file_size,
            extraction_time_ms=project.extraction_time_ms,
        )


PROJECTS: dict[str, ProjectRecord] = {}
_PROJECTS_LOCK = Lock()


def save_project(project: ProjectRecord) -> ProjectRecord:
    with _PROJECTS_LOCK:
        PROJECTS[project.id] = project

    return project


def get_project(project_id: str) -> ProjectRecord | None:
    with _PROJECTS_LOCK:
        return PROJECTS.get(project_id)


def save_generated_paper(
    project_id: str,
    generated_paper: GeneratedPaper,
    generation_metadata: GenerationMetadata,
) -> ProjectRecord | None:
    with _PROJECTS_LOCK:
        project = PROJECTS.get(project_id)
        if project is None:
            return None

        updated_project = project.model_copy(
            update={
                "generated_sections": PaperSections(
                    abstract=generated_paper.abstract,
                    introduction=generated_paper.introduction,
                    methodology=generated_paper.methodology,
                    conclusion=generated_paper.conclusion,
                ),
                "generated_paper": generated_paper,
                "generation_metadata": generation_metadata,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        PROJECTS[project_id] = updated_project
        return updated_project
