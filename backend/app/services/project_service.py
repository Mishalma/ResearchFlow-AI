from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging
import re
from uuid import uuid4

from app.core.exceptions import (
    ExportArtifactNotFoundError,
    FigureNotFoundError,
    ProjectExportContentError,
    ProjectNotFoundError,
)
from app.models.generation import GeneratedPaper, GenerationMetadata, ResearchPaperSchema
from app.models.project import ExportArtifact, FigureRecord, ProjectRecord
from app.schemas.project_schema import ProjectResponse, ProjectSummaryResponse
from app.services.paper_service import (
    build_editor_display_text,
    build_latex_ready_text,
    parse_editor_content,
    validate_research_paper,
)
from persistence import get_project_repository
from core.config import get_settings

logger = logging.getLogger("papereasy.backend.project")
settings = get_settings()

INVALID_FILE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _safe_file_name(title: str) -> str:
    slug = INVALID_FILE_NAME_CHARS.sub("-", title.strip()).strip("-._")
    return slug or "research-paper"


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [value.strip() for value in values if value.strip()]


def _derive_project_title(project: ProjectRecord) -> str:
    title = project.title.strip()
    if title:
        return title
    return Path(project.file_name).stem or "Research Paper"


def _derive_project_content(project: ProjectRecord) -> str:
    content = project.content.strip()
    if content:
        return content

    if project.edited_paper is not None:
        return build_editor_display_text(project.edited_paper)

    if project.generated_paper is not None:
        return project.generated_paper.formatted_text.strip()

    return project.extracted_text.strip()


def _normalize_project(project: ProjectRecord) -> ProjectRecord:
    created_at = project.created_at or _timestamp()
    updated_at = project.updated_at or created_at
    title = _derive_project_title(project)
    content = _derive_project_content(project)
    file_name = project.file_name or f"{_safe_file_name(title)}.txt"

    return project.model_copy(
        update={
            "title": title,
            "owner_uid": project.owner_uid.strip(),
            "owner_email": project.owner_email.strip().lower(),
            "authors": _normalize_string_list(project.authors),
            "keywords": _normalize_string_list(project.keywords),
            "content": content,
            "display_paper_text": project.display_paper_text.strip() or content,
            "latex_ready": project.latex_ready.strip() or content,
            "file_name": file_name,
            "created_at": created_at,
            "updated_at": updated_at,
        }
    )


def _assert_project_owner(project: ProjectRecord, owner_uid: str) -> ProjectRecord:
    if project.owner_uid != owner_uid:
        raise ProjectNotFoundError(project.id)
    return project


def persist_project(project: ProjectRecord) -> ProjectRecord:
    repository = get_project_repository()
    normalized_project = _normalize_project(project)
    saved_project = repository.save(normalized_project)
    logger.info("Persisted project %s", normalized_project.id)
    return saved_project


def get_project(project_id: str, owner_uid: str | None = None) -> ProjectRecord:
    repository = get_project_repository()
    project = repository.get(project_id)
    if project is None:
        raise ProjectNotFoundError(project_id)

    if owner_uid is not None:
        _assert_project_owner(project, owner_uid)

    return project


def list_projects(owner_uid: str) -> list[ProjectRecord]:
    repository = get_project_repository()
    projects = repository.list(owner_uid)
    return sorted(
        projects,
        key=lambda project: project.updated_at,
        reverse=True,
    )


def list_project_responses(owner_uid: str) -> list[ProjectSummaryResponse]:
    return [ProjectSummaryResponse.from_project(project) for project in list_projects(owner_uid)]


def get_project_response(project_id: str, owner_uid: str) -> ProjectResponse:
    project = get_project(project_id, owner_uid)
    return ProjectResponse.from_project(project)


def get_effective_paper(project: ProjectRecord) -> ResearchPaperSchema:
    paper = project.edited_paper or (project.generated_paper.paper if project.generated_paper else None)
    if paper is None:
        raise ProjectExportContentError(project.id)

    issues = validate_research_paper(paper, require_references=False)
    if issues:
        raise ProjectExportContentError(
            project.id,
            message=f"Project '{project.id}' is missing required IEEE content: {'; '.join(issues)}",
        )

    return paper


def get_project_title(project: ProjectRecord) -> str:
    return _derive_project_title(project)


def get_project_references(project: ProjectRecord) -> list[str]:
    try:
        return get_effective_paper(project).references
    except ProjectExportContentError:
        return []


def save_generated_paper(
    project_id: str,
    owner_uid: str,
    generated_paper: GeneratedPaper,
    generation_metadata: GenerationMetadata,
    generated_figures: list[dict] | None = None,
    generated_tables: list[dict] | None = None,
) -> ProjectRecord:
    project = get_project(project_id, owner_uid)
    display_paper_text = generated_paper.formatted_text.strip() or build_editor_display_text(generated_paper.paper)
    normalized_generated_figures = list(generated_figures or [])
    normalized_generated_tables = list(generated_tables or [])
    generated_figure_assets = {
        entry["spec"]["id"]: entry.get("asset_path")
        or str(settings.local_projects_dir / project_id / "generated_figures" / f"{entry['spec']['id']}.png")
        for entry in normalized_generated_figures
        if isinstance(entry, dict) and isinstance(entry.get("spec"), dict)
    }
    updated_project = project.model_copy(
        update={
            "title": generated_paper.paper.title,
            "keywords": list(generated_paper.paper.keywords),
            "generated_paper": generated_paper,
            "edited_paper": None,
            "generation_metadata": generation_metadata,
            "content": display_paper_text,
            "display_paper_text": display_paper_text,
            "latex_ready": generated_paper.latex_ready,
            "generated_figures": normalized_generated_figures,
            "generated_tables": normalized_generated_tables,
            "generated_figure_assets": generated_figure_assets,
            "updated_at": _timestamp(),
        }
    )
    return persist_project(updated_project)


def save_project_generated_visuals(
    project_id: str,
    owner_uid: str,
    *,
    generated_figures: list[dict],
    generated_tables: list[dict],
) -> ProjectRecord:
    """Persist generated figure/table metadata without touching manual uploads."""

    project = get_project(project_id, owner_uid)
    normalized_generated_figures = list(generated_figures)
    normalized_generated_tables = list(generated_tables)
    generated_figure_assets = {
        entry["spec"]["id"]: entry.get("asset_path")
        or str(settings.local_projects_dir / project_id / "generated_figures" / f"{entry['spec']['id']}.png")
        for entry in normalized_generated_figures
        if isinstance(entry, dict) and isinstance(entry.get("spec"), dict)
    }
    updated_project = project.model_copy(
        update={
            "generated_figures": normalized_generated_figures,
            "generated_tables": normalized_generated_tables,
            "generated_figure_assets": generated_figure_assets,
            "updated_at": _timestamp(),
        }
    )
    return persist_project(updated_project)


def save_project_content(
    *,
    owner_uid: str,
    owner_email: str,
    project_id: str | None,
    title: str,
    authors: list[str] | None,
    keywords: list[str] | None,
    content: str | None,
    paper: ResearchPaperSchema | None,
) -> ProjectRecord:
    normalized_title = title.strip()
    normalized_authors = _normalize_string_list(authors)
    normalized_keywords = _normalize_string_list(keywords)
    normalized_content = (content or "").strip()
    updated_at = _timestamp()

    if project_id:
        project = get_project(project_id, owner_uid)
        fallback_keywords = normalized_keywords or project.keywords or (
            project.generated_paper.paper.keywords if project.generated_paper else []
        )
        fallback_references = get_project_references(project)
        parsed_paper = paper or parse_editor_content(
            title=normalized_title,
            content=normalized_content or project.display_paper_text,
            fallback_keywords=fallback_keywords,
            fallback_references=fallback_references,
        )
        display_paper_text = build_editor_display_text(parsed_paper)
        updated_project = project.model_copy(
            update={
                "title": normalized_title,
                "owner_uid": owner_uid,
                "owner_email": owner_email,
                "authors": normalized_authors,
                "keywords": normalized_keywords or parsed_paper.keywords,
                "content": display_paper_text,
                "display_paper_text": display_paper_text,
                "latex_ready": build_latex_ready_text(parsed_paper),
                "edited_paper": parsed_paper,
                "updated_at": updated_at,
            }
        )
        saved_project = persist_project(updated_project)
        logger.info("Saved project content for %s", project_id)
        return saved_project

    parsed_paper = paper or parse_editor_content(
        title=normalized_title,
        content=normalized_content,
        fallback_keywords=normalized_keywords,
        fallback_references=[],
    )
    display_paper_text = build_editor_display_text(parsed_paper)
    created_at = updated_at

    project = ProjectRecord(
        id=str(uuid4()),
        title=normalized_title,
        owner_uid=owner_uid,
        owner_email=owner_email,
        authors=normalized_authors,
        keywords=normalized_keywords or parsed_paper.keywords,
        content=display_paper_text,
        display_paper_text=display_paper_text,
        latex_ready=build_latex_ready_text(parsed_paper),
        generated_paper=None,
        edited_paper=parsed_paper,
        file_name=f"{_safe_file_name(normalized_title)}.txt",
        file_path="",
        extracted_text=display_paper_text,
        file_type="manual",
        file_size=len(display_paper_text.encode("utf-8")),
        extraction_time_ms=0.0,
        created_at=created_at,
        updated_at=created_at,
    )
    saved_project = persist_project(project)
    logger.info("Created project %s from editor save", saved_project.id)
    return saved_project


def add_figure(project_id: str, owner_uid: str, figure: FigureRecord) -> ProjectRecord:
    project = get_project(project_id, owner_uid)
    updated_project = project.model_copy(
        update={
            "figures": [*project.figures, figure],
            "updated_at": _timestamp(),
        }
    )
    saved_project = persist_project(updated_project)
    logger.info("Attached figure %s to project %s", figure.id, project_id)
    return saved_project


def get_project_figure(project_id: str, owner_uid: str, figure_id: str) -> FigureRecord:
    project = get_project(project_id, owner_uid)
    for figure in project.figures:
        if figure.id == figure_id:
            return figure

    raise FigureNotFoundError(project_id, figure_id)


def record_export(project_id: str, owner_uid: str, artifact: ExportArtifact) -> ProjectRecord:
    project = get_project(project_id, owner_uid)
    updated_project = project.model_copy(
        update={
            "exports": [*project.exports, artifact],
            "updated_at": _timestamp(),
        }
    )
    saved_project = persist_project(updated_project)
    logger.info("Recorded %s export for project %s", artifact.format, project_id)
    return saved_project


def get_project_export(project_id: str, owner_uid: str, export_id: str) -> ExportArtifact:
    project = get_project(project_id, owner_uid)
    for artifact in project.exports:
        if artifact.id == export_id:
            return artifact

    raise ExportArtifactNotFoundError(project_id, export_id)
