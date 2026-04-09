from __future__ import annotations

from functools import lru_cache

from core.config import Settings, get_settings
from core.exceptions import PersistenceConfigurationError
from persistence.base import ObjectStorage, ProjectRepository
from persistence.gcp import FirestoreProjectRepository, GCSObjectStorage
from persistence.local import LocalObjectStorage, LocalProjectRepository


@lru_cache(maxsize=4)
def _build_project_repository(settings: Settings) -> ProjectRepository:
    if settings.persistence_backend == "gcp":
        if not settings.google_cloud_project:
            raise PersistenceConfigurationError(
                "GOOGLE_CLOUD_PROJECT is required when PERSISTENCE_BACKEND=gcp."
            )
        if not settings.firestore_projects_collection:
            raise PersistenceConfigurationError(
                "FIRESTORE_PROJECTS_COLLECTION is required when PERSISTENCE_BACKEND=gcp."
            )

        return FirestoreProjectRepository(
            project_id=settings.google_cloud_project,
            collection_name=settings.firestore_projects_collection,
        )

    return LocalProjectRepository(settings.local_projects_dir)


@lru_cache(maxsize=4)
def _build_object_storage(settings: Settings) -> ObjectStorage:
    if settings.persistence_backend == "gcp":
        if not settings.google_cloud_project:
            raise PersistenceConfigurationError(
                "GOOGLE_CLOUD_PROJECT is required when PERSISTENCE_BACKEND=gcp."
            )
        if not settings.gcs_bucket_name:
            raise PersistenceConfigurationError(
                "GCS_BUCKET_NAME is required when PERSISTENCE_BACKEND=gcp."
            )

        return GCSObjectStorage(
            project_id=settings.google_cloud_project,
            bucket_name=settings.gcs_bucket_name,
        )

    return LocalObjectStorage(settings.base_dir)


def get_project_repository(settings: Settings | None = None) -> ProjectRepository:
    resolved_settings = settings or get_settings()
    return _build_project_repository(resolved_settings)


def get_object_storage(settings: Settings | None = None) -> ObjectStorage:
    resolved_settings = settings or get_settings()
    return _build_object_storage(resolved_settings)
