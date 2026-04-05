from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.project import FigureRecord, FigureSection


class FigureUploadResponse(BaseModel):
    project_id: str
    figure: FigureRecord


class FigureUploadData(BaseModel):
    project_id: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    section: FigureSection
