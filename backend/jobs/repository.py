from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol

from core.config import Settings, get_settings
from core.exceptions import PersistenceConfigurationError, PersistenceError
from models.job import JobRecord

logger = logging.getLogger("papereasy.backend.jobs.repository")

ACTIVE_JOB_STATUSES = {
    "CREATED",
    "GENERATION_REQUESTED",
    "GENERATING",
    "GENERATED",
    "VALIDATION_REQUESTED",
    "VALIDATING",
    "FIX_REQUESTED",
    "FIXING",
    "FINALIZING",
}


class JobRepository(Protocol):
    def save(self, job: JobRecord) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def find_by_idempotency(
        self,
        *,
        user_id: str,
        project_id: str,
        idempotency_key: str,
    ) -> JobRecord | None: ...

    def find_active_by_user(self, user_id: str) -> JobRecord | None: ...


class LocalJobRepository(JobRepository):
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def save(self, job: JobRecord) -> JobRecord:
        with self._lock:
            self._job_path(job.job_id).write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return job

    def get(self, job_id: str) -> JobRecord | None:
        path = self._job_path(job_id)
        with self._lock:
            if not path.exists():
                return None
            return JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _list_all(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for path in sorted(self.jobs_dir.glob("*.json")):
            jobs.append(JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        return jobs

    def find_by_idempotency(
        self,
        *,
        user_id: str,
        project_id: str,
        idempotency_key: str,
    ) -> JobRecord | None:
        with self._lock:
            for job in reversed(self._list_all()):
                if (
                    job.user_id == user_id
                    and job.project_id == project_id
                    and job.idempotency_key == idempotency_key
                ):
                    return job
        return None

    def find_active_by_user(self, user_id: str) -> JobRecord | None:
        with self._lock:
            active_jobs = [
                job
                for job in self._list_all()
                if job.user_id == user_id and job.status in ACTIVE_JOB_STATUSES
            ]
        if not active_jobs:
            return None
        active_jobs.sort(key=lambda job: job.timestamps.created_at, reverse=True)
        return active_jobs[0]


class FirestoreJobRepository(JobRepository):
    def __init__(self, *, project_id: str, collection_name: str):
        try:
            from google.cloud import firestore
        except ImportError as exc:  # pragma: no cover - env dependent
            raise PersistenceConfigurationError(
                "google-cloud-firestore is required for Firestore workflow jobs."
            ) from exc

        self._client = firestore.Client(project=project_id)
        self._collection = self._client.collection(collection_name)

    def save(self, job: JobRecord) -> JobRecord:
        try:
            self._collection.document(job.job_id).set(job.model_dump(mode="python"))
        except Exception as exc:  # pragma: no cover - network/env dependent
            logger.exception(
                "Firestore save failed for job %s in collection %s",
                job.job_id,
                self._collection.id,
            )
            raise PersistenceError("Unable to save the workflow job.") from exc
        return job

    def get(self, job_id: str) -> JobRecord | None:
        try:
            snapshot = self._collection.document(job_id).get()
        except Exception as exc:  # pragma: no cover - network/env dependent
            logger.exception(
                "Firestore get failed for job %s in collection %s",
                job_id,
                self._collection.id,
            )
            raise PersistenceError("Unable to load the workflow job.") from exc

        if not snapshot.exists:
            return None

        return JobRecord.model_validate(snapshot.to_dict() or {})

    def find_by_idempotency(
        self,
        *,
        user_id: str,
        project_id: str,
        idempotency_key: str,
    ) -> JobRecord | None:
        try:
            query = (
                self._collection.where("user_id", "==", user_id)
                .where("project_id", "==", project_id)
                .where("idempotency_key", "==", idempotency_key)
                .limit(1)
            )
            snapshots = list(query.stream())
        except Exception as exc:  # pragma: no cover - network/env dependent
            logger.exception(
                "Firestore idempotency lookup failed for user=%s project=%s in collection %s",
                user_id,
                project_id,
                self._collection.id,
            )
            raise PersistenceError("Unable to query workflow jobs.") from exc

        if not snapshots:
            return None

        return JobRecord.model_validate(snapshots[0].to_dict() or {})

    def find_active_by_user(self, user_id: str) -> JobRecord | None:
        try:
            query = self._collection.where("user_id", "==", user_id).where(
                "status",
                "in",
                list(ACTIVE_JOB_STATUSES),
            )
            snapshots = list(query.stream())
        except Exception as exc:  # pragma: no cover - network/env dependent
            logger.exception(
                "Firestore active-job lookup failed for user=%s in collection %s",
                user_id,
                self._collection.id,
            )
            raise PersistenceError("Unable to query active workflow jobs.") from exc

        if not snapshots:
            return None

        jobs = [JobRecord.model_validate(snapshot.to_dict() or {}) for snapshot in snapshots]
        jobs.sort(key=lambda job: job.timestamps.created_at, reverse=True)
        return jobs[0]


@lru_cache(maxsize=4)
def _build_job_repository(settings: Settings) -> JobRepository:
    if settings.persistence_backend == "gcp":
        if not settings.google_cloud_project:
            raise PersistenceConfigurationError(
                "GOOGLE_CLOUD_PROJECT is required when PERSISTENCE_BACKEND=gcp."
            )
        if not settings.firestore_jobs_collection:
            raise PersistenceConfigurationError(
                "FIRESTORE_JOBS_COLLECTION is required when PERSISTENCE_BACKEND=gcp."
            )

        return FirestoreJobRepository(
            project_id=settings.google_cloud_project,
            collection_name=settings.firestore_jobs_collection,
        )

    return LocalJobRepository(settings.local_jobs_dir)


def get_job_repository(settings: Settings | None = None) -> JobRepository:
    resolved_settings = settings or get_settings()
    return _build_job_repository(resolved_settings)
