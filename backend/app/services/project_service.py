from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging

from app.core.exceptions import (
    ProjectExportContentError,
    ProjectNotFoundError,
    ProjectSectionsUnavailableError,
)
from app.models.generation import GeneratedPaper, PaperSections
from app.models.project import ExportArtifact, FigureRecord, ProjectRecord
from app.schemas.project_schema import ProjectResponse, SectionUpdate
from models.project import _PROJECTS_LOCK, PROJECTS

logger = logging.getLogger("papereasy.backend.project")


SECTION_ORDER = (
    ("Abstract", "abstract"),
    ("Introduction", "introduction"),
    ("Methodology", "methodology"),
    ("Conclusion", "conclusion"),
)


def _build_formatted_paper(sections: PaperSections, references: list[str]) -> str:
    references_block = "\n".join(references) if references else "No references available."
    parts = ["RESEARCH PAPER"]

    for title, key in SECTION_ORDER:
        parts.extend(["", title, getattr(sections, key)])

    parts.extend(["", "References", references_block])
    return "\n".join(parts).strip()


def _merge_sections(base_sections: PaperSections, updates: SectionUpdate) -> PaperSections:
    merged = base_sections.model_dump()
    merged.update(updates.model_dump(exclude_none=True))
    return PaperSections(**merged)


def _sync_generated_paper(
    project: ProjectRecord,
    sections: PaperSections,
) -> GeneratedPaper | None:
    if project.generated_paper is None:
        return None

    return project.generated_paper.model_copy(
        update={
            "abstract": sections.abstract,
            "introduction": sections.introduction,
            "methodology": sections.methodology,
            "conclusion": sections.conclusion,
            "formatted_paper": _build_formatted_paper(
                sections,
                project.generated_paper.references,
            ),
        }
    )


def _timestamp() -> datetime:
    return datetime.now(timezone.utc)


def get_project(project_id: str) -> ProjectRecord:
    with _PROJECTS_LOCK:
        project = PROJECTS.get(project_id)

    if project is None:
        raise ProjectNotFoundError(project_id)

    return project


def get_project_response(project_id: str) -> ProjectResponse:
    project = get_project(project_id)
    return ProjectResponse.from_project(project)


def get_effective_sections(project: ProjectRecord) -> PaperSections:
    sections = project.edited_sections or project.generated_sections
    if sections is None:
        raise ProjectExportContentError(project.id)

    return sections


def get_project_title(project: ProjectRecord) -> str:
    return Path(project.file_name).stem or "Research Paper"


def get_project_references(project: ProjectRecord) -> list[str]:
    if project.generated_paper is None:
        return []

    return project.generated_paper.references


def save_project(project_id: str, sections: SectionUpdate) -> ProjectRecord:
    with _PROJECTS_LOCK:
        project = PROJECTS.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        base_sections = project.edited_sections or project.generated_sections
        if base_sections is None:
            raise ProjectSectionsUnavailableError(project_id)

        merged_sections = _merge_sections(base_sections, sections)
        updated_at = _timestamp()
        synced_generated_paper = _sync_generated_paper(project, merged_sections)

        updated_project = project.model_copy(
            update={
                "edited_sections": merged_sections,
                "generated_paper": synced_generated_paper,
                "updated_at": updated_at,
            }
        )
        PROJECTS[project_id] = updated_project

    logger.info("Saved edited sections for project %s", project_id)
    return updated_project


def add_figure(project_id: str, figure: FigureRecord) -> ProjectRecord:
    with _PROJECTS_LOCK:
        project = PROJECTS.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        updated_project = project.model_copy(
            update={
                "figures": [*project.figures, figure],
                "updated_at": _timestamp(),
            }
        )
        PROJECTS[project_id] = updated_project

    logger.info("Attached figure %s to project %s", figure.id, project_id)
    return updated_project


def record_export(project_id: str, artifact: ExportArtifact) -> ProjectRecord:
    with _PROJECTS_LOCK:
        project = PROJECTS.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        updated_project = project.model_copy(
            update={
                "exports": [*project.exports, artifact],
                "updated_at": _timestamp(),
            }
        )
        PROJECTS[project_id] = updated_project

    logger.info("Recorded %s export for project %s", artifact.format, project_id)
    return updated_project
