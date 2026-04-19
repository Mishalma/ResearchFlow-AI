from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import AuthenticatedRequestUser, get_authenticated_user
from app.core.config import get_settings
from app.services.project_service import get_project, save_project_generated_visuals
from figure_table.generator import FigureGenerator
from figure_table.models import FigureSpec, RenderedFigure

router = APIRouter(tags=["generated-figures"])
settings = get_settings()


class FigureRegenerateRequest(BaseModel):
    updated_data: dict[str, Any] = Field(default_factory=dict)


class GeneratedFiguresResponse(BaseModel):
    figures: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    figure_count: int = 0
    table_count: int = 0


class FigureRegenerateResponse(BaseModel):
    figure: dict[str, Any]
    success: bool


@router.get("/projects/{project_id}/figures", response_model=GeneratedFiguresResponse)
async def get_generated_figures(
    project_id: str,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> GeneratedFiguresResponse:
    project = get_project(project_id, current_user.user_id)
    return GeneratedFiguresResponse(
        figures=list(project.generated_figures),
        tables=list(project.generated_tables),
        figure_count=len(project.generated_figures),
        table_count=len(project.generated_tables),
    )


@router.post("/projects/{project_id}/figures/{figure_id}/regenerate", response_model=FigureRegenerateResponse)
async def regenerate_generated_figure(
    project_id: str,
    figure_id: str,
    request: FigureRegenerateRequest,
    current_user: AuthenticatedRequestUser = Depends(get_authenticated_user),
) -> FigureRegenerateResponse:
    project = get_project(project_id, current_user.user_id)
    generator = FigureGenerator()

    figure_entry, source_collection = _find_generated_entry(project, figure_id)
    if figure_entry is None:
        raise HTTPException(status_code=404, detail=f"Generated figure '{figure_id}' was not found.")

    spec_payload = dict(figure_entry.get("spec") or {})
    spec_payload["data"] = {
        **dict(spec_payload.get("data") or {}),
        **dict(request.updated_data or {}),
    }
    spec = FigureSpec.model_validate(spec_payload)
    rendered = await generator.render_one(spec)
    updated_entry = rendered.model_dump(mode="python")
    asset_path = _persist_generated_asset(project_id=project_id, rendered=rendered)
    if asset_path:
        updated_entry["asset_path"] = asset_path

    if source_collection == "figures":
        updated_figures = [
            updated_entry if _entry_id(entry) == figure_id else entry
            for entry in project.generated_figures
        ]
        updated_tables = list(project.generated_tables)
    else:
        updated_figures = list(project.generated_figures)
        updated_tables = [
            updated_entry if _entry_id(entry) == figure_id else entry
            for entry in project.generated_tables
        ]

    save_project_generated_visuals(
        project_id=project_id,
        owner_uid=current_user.user_id,
        generated_figures=updated_figures,
        generated_tables=updated_tables,
    )
    return FigureRegenerateResponse(figure=updated_entry, success=rendered.render_success)


def _find_generated_entry(project, figure_id: str) -> tuple[dict[str, Any] | None, str | None]:
    for entry in project.generated_figures:
        if _entry_id(entry) == figure_id:
            return entry, "figures"
    for entry in project.generated_tables:
        if _entry_id(entry) == figure_id:
            return entry, "tables"
    return None, None


def _entry_id(entry: dict[str, Any]) -> str:
    spec = entry.get("spec") or {}
    return str(spec.get("id", "")).strip()


def _persist_generated_asset(*, project_id: str, rendered: RenderedFigure) -> str | None:
    if not rendered.render_success or not rendered.png_base64:
        return None
    asset_dir = settings.local_projects_dir / project_id / "generated_figures"
    asset_dir.mkdir(parents=True, exist_ok=True)
    target_path = asset_dir / f"{rendered.spec.id}.png"
    target_path.write_bytes(base64.b64decode(rendered.png_base64))
    return str(target_path)
