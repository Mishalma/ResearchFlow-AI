from __future__ import annotations

import json
import mimetypes
import shutil
from pathlib import Path
from threading import Lock

from models.project import ProjectRecord
from persistence.base import DownloadedObject, ObjectStorage, ProjectRepository, StoredObject


class LocalProjectRepository(ProjectRepository):
    def __init__(self, projects_dir: Path):
        self.projects_dir = projects_dir
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _project_path(self, project_id: str) -> Path:
        return self.projects_dir / f"{project_id}.json"

    def save(self, project: ProjectRecord) -> ProjectRecord:
        with self._lock:
            self._project_path(project.id).write_text(
                project.model_dump_json(indent=2),
                encoding="utf-8",
            )
        return project

    def get(self, project_id: str) -> ProjectRecord | None:
        path = self._project_path(project_id)
        with self._lock:
            if not path.exists():
                return None
            return ProjectRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list(self, owner_uid: str | None = None) -> list[ProjectRecord]:
        with self._lock:
            projects: list[ProjectRecord] = []
            for path in sorted(self.projects_dir.glob("*.json")):
                project = ProjectRecord.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if owner_uid and project.owner_uid != owner_uid:
                    continue
                projects.append(project)
        return projects


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def _resolve_path(self, key: str) -> Path:
        return (self.root_dir / key).resolve()

    def upload_file(
        self,
        key: str,
        source_path: Path,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        destination = self._resolve_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        size = destination.stat().st_size
        return StoredObject(
            key=key,
            storage_uri=str(destination),
            content_type=content_type or mimetypes.guess_type(destination.name)[0],
            size=size,
        )

    def download_bytes(self, key: str) -> DownloadedObject:
        path = self._resolve_path(key)
        content = path.read_bytes()
        return DownloadedObject(
            key=key,
            content=content,
            content_type=mimetypes.guess_type(path.name)[0],
            storage_uri=str(path),
            size=len(content),
        )

    def download_to_path(self, key: str, destination: Path) -> Path:
        source = self._resolve_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    def delete(self, key: str) -> None:
        path = self._resolve_path(key)
        path.unlink(missing_ok=True)

    def get_uri(self, key: str) -> str:
        return str(self._resolve_path(key))
