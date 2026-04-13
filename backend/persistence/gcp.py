from __future__ import annotations

import logging
from pathlib import Path

from core.exceptions import PersistenceConfigurationError, PersistenceError
from models.project import ProjectRecord
from persistence.base import DownloadedObject, ObjectStorage, ProjectRepository, StoredObject

logger = logging.getLogger("papereasy.backend.persistence.gcp")


class FirestoreProjectRepository(ProjectRepository):
    def __init__(self, *, project_id: str, collection_name: str):
        try:
            from google.cloud import firestore
        except ImportError as exc:
            raise PersistenceConfigurationError(
                "google-cloud-firestore is required for GCP project persistence."
            ) from exc

        self._client = firestore.Client(project=project_id)
        self._collection = self._client.collection(collection_name)

    def save(self, project: ProjectRecord) -> ProjectRecord:
        try:
            self._collection.document(project.id).set(project.model_dump(mode="python"))
        except Exception as exc:
            logger.exception(
                "Firestore save failed for project %s in collection %s",
                project.id,
                self._collection.id,
            )
            raise PersistenceError("Unable to save the project to Firestore.") from exc
        return project

    def get(self, project_id: str) -> ProjectRecord | None:
        try:
            snapshot = self._collection.document(project_id).get()
        except Exception as exc:
            logger.exception(
                "Firestore get failed for project %s in collection %s",
                project_id,
                self._collection.id,
            )
            raise PersistenceError("Unable to load the project from Firestore.") from exc

        if not snapshot.exists:
            return None

        return ProjectRecord.model_validate(snapshot.to_dict() or {})

    def list(self, owner_uid: str | None = None) -> list[ProjectRecord]:
        try:
            query = self._collection
            if owner_uid:
                query = query.where("owner_uid", "==", owner_uid)
            snapshots = list(query.stream())
        except Exception as exc:
            logger.exception(
                "Firestore list failed for owner %s in collection %s",
                owner_uid,
                self._collection.id,
            )
            raise PersistenceError("Unable to list projects from Firestore.") from exc

        return [ProjectRecord.model_validate(snapshot.to_dict() or {}) for snapshot in snapshots]


class GCSObjectStorage(ObjectStorage):
    def __init__(self, *, project_id: str, bucket_name: str):
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise PersistenceConfigurationError(
                "google-cloud-storage is required for GCP object storage."
            ) from exc

        self._client = storage.Client(project=project_id)
        self._bucket = self._client.bucket(bucket_name)

    def upload_file(
        self,
        key: str,
        source_path: Path,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        blob = self._bucket.blob(key)
        try:
            blob.upload_from_filename(str(source_path), content_type=content_type)
        except Exception as exc:
            logger.exception(
                "Cloud Storage upload failed for key %s to bucket %s using project %s from %s",
                key,
                self._bucket.name,
                self._client.project,
                source_path,
            )
            raise PersistenceError(f"Unable to upload object '{key}' to Cloud Storage.") from exc

        return StoredObject(
            key=key,
            storage_uri=f"gs://{self._bucket.name}/{key}",
            content_type=blob.content_type or content_type,
            size=source_path.stat().st_size,
        )

    def download_bytes(self, key: str) -> DownloadedObject:
        blob = self._bucket.blob(key)
        try:
            content = blob.download_as_bytes()
            blob.reload()
        except Exception as exc:
            logger.exception(
                "Cloud Storage download failed for key %s from bucket %s using project %s",
                key,
                self._bucket.name,
                self._client.project,
            )
            raise PersistenceError(f"Unable to download object '{key}' from Cloud Storage.") from exc

        return DownloadedObject(
            key=key,
            content=content,
            content_type=blob.content_type,
            storage_uri=f"gs://{self._bucket.name}/{key}",
            size=len(content),
        )

    def download_to_path(self, key: str, destination: Path) -> Path:
        blob = self._bucket.blob(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            blob.download_to_filename(str(destination))
        except Exception as exc:
            logger.exception(
                "Cloud Storage download-to-file failed for key %s from bucket %s using project %s",
                key,
                self._bucket.name,
                self._client.project,
            )
            raise PersistenceError(f"Unable to download object '{key}' from Cloud Storage.") from exc

        return destination

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(key)
        try:
            blob.delete(if_generation_match=None)
        except Exception:
            return

    def get_uri(self, key: str) -> str:
        return f"gs://{self._bucket.name}/{key}"
