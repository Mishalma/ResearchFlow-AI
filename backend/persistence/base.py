from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from models.project import ProjectRecord


@dataclass(frozen=True)
class StoredObject:
    key: str
    storage_uri: str
    content_type: str | None
    size: int


@dataclass(frozen=True)
class DownloadedObject:
    key: str
    content: bytes
    content_type: str | None
    storage_uri: str
    size: int


class ObjectStorage(Protocol):
    def upload_file(
        self,
        key: str,
        source_path: Path,
        *,
        content_type: str | None = None,
    ) -> StoredObject: ...

    def download_bytes(self, key: str) -> DownloadedObject: ...

    def download_to_path(self, key: str, destination: Path) -> Path: ...

    def delete(self, key: str) -> None: ...

    def get_uri(self, key: str) -> str: ...


class ProjectRepository(Protocol):
    def save(self, project: ProjectRecord) -> ProjectRecord: ...

    def get(self, project_id: str) -> ProjectRecord | None: ...

    def list(self, owner_uid: str | None = None) -> list[ProjectRecord]: ...
