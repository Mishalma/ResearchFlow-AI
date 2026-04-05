from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.project import ExportArtifact


class ExportRequest(BaseModel):
    project_id: str = Field(min_length=1)


class ExportResponse(BaseModel):
    project_id: str
    artifact: ExportArtifact
