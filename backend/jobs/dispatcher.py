from __future__ import annotations

import asyncio
import json
import logging
from threading import Lock
from typing import Awaitable, Callable, Protocol
from uuid import uuid4

from core.config import Settings, get_settings
from core.exceptions import WorkflowConfigurationError
from models.job import GenerationTaskRequest, JobRecord, WorkflowActiveTask

logger = logging.getLogger("papereasy.backend.jobs.dispatcher")

_active_local_tasks: dict[str, asyncio.Task[None]] = {}
_active_local_tasks_lock = Lock()


class JobDispatcher(Protocol):
    async def dispatch_generation(self, job: JobRecord) -> WorkflowActiveTask: ...


class LocalJobDispatcher:
    def __init__(
        self,
        *,
        runner: Callable[[GenerationTaskRequest], Awaitable[None]],
    ):
        self._runner = runner

    async def dispatch_generation(self, job: JobRecord) -> WorkflowActiveTask:
        task_request = GenerationTaskRequest(
            task_id=f"local-{job.job_id}-{uuid4().hex}",
            job_id=job.job_id,
            project_id=job.project_id,
            user_id=job.user_id,
            idempotency_key=job.idempotency_key,
        )

        loop = asyncio.get_running_loop()
        task = loop.create_task(self._runner(task_request))
        with _active_local_tasks_lock:
            _active_local_tasks[job.job_id] = task

        def _cleanup(_task: asyncio.Task[None]) -> None:
            with _active_local_tasks_lock:
                _active_local_tasks.pop(job.job_id, None)

        task.add_done_callback(_cleanup)

        return WorkflowActiveTask(
            task_id=task_request.task_id,
            queue_name="local-in-process",
            worker_target="jobs.service.run_generation_task",
            attempt=1,
        )


class CloudTasksJobDispatcher:
    def __init__(
        self,
        *,
        settings: Settings,
    ):
        try:
            from google.cloud import tasks_v2
        except ImportError as exc:  # pragma: no cover - env dependent
            raise WorkflowConfigurationError(
                "google-cloud-tasks is required when WORKFLOW_DISPATCH_BACKEND=cloud_tasks."
            ) from exc

        if not settings.workflow_cloud_tasks_project:
            raise WorkflowConfigurationError(
                "WORKFLOW_CLOUD_TASKS_PROJECT is required for Cloud Tasks dispatch."
            )
        if not settings.workflow_cloud_tasks_location:
            raise WorkflowConfigurationError(
                "WORKFLOW_CLOUD_TASKS_LOCATION is required for Cloud Tasks dispatch."
            )
        if not settings.workflow_cloud_tasks_queue:
            raise WorkflowConfigurationError(
                "WORKFLOW_CLOUD_TASKS_QUEUE is required for Cloud Tasks dispatch."
            )
        if not settings.workflow_cloud_tasks_target_url:
            raise WorkflowConfigurationError(
                "WORKFLOW_CLOUD_TASKS_TARGET_URL is required for Cloud Tasks dispatch."
            )
        if not settings.workflow_cloud_tasks_service_account_email:
            raise WorkflowConfigurationError(
                "WORKFLOW_CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL is required for Cloud Tasks dispatch."
            )

        self._tasks_v2 = tasks_v2
        self._client = tasks_v2.CloudTasksClient()
        self._settings = settings
        self._queue_path = self._client.queue_path(
            settings.workflow_cloud_tasks_project,
            settings.workflow_cloud_tasks_location,
            settings.workflow_cloud_tasks_queue,
        )

    async def dispatch_generation(self, job: JobRecord) -> WorkflowActiveTask:
        task_request = GenerationTaskRequest(
            task_id=f"cloud-task-{job.job_id}-{uuid4().hex}",
            job_id=job.job_id,
            project_id=job.project_id,
            user_id=job.user_id,
            idempotency_key=job.idempotency_key,
        )
        target_url = self._settings.workflow_cloud_tasks_target_url.rstrip("/") + "/internal/jobs/run"
        payload = task_request.model_dump(mode="json")
        task = {
            "http_request": {
                "http_method": self._tasks_v2.HttpMethod.POST,
                "url": target_url,
                "headers": {
                    "Content-Type": "application/json",
                    "X-PaperEasy-Job-Id": job.job_id,
                    "X-PaperEasy-Task-Id": task_request.task_id,
                },
                "body": json.dumps(payload).encode("utf-8"),
                "oidc_token": {
                    "service_account_email": self._settings.workflow_cloud_tasks_service_account_email,
                    "audience": self._settings.workflow_cloud_tasks_target_url.rstrip("/"),
                },
            }
        }

        def _create_task() -> None:
            self._client.create_task(parent=self._queue_path, task=task)

        await asyncio.to_thread(_create_task)

        return WorkflowActiveTask(
            task_id=task_request.task_id,
            queue_name=self._settings.workflow_cloud_tasks_queue,
            worker_target=target_url,
            attempt=1,
        )


def get_job_dispatcher(
    *,
    runner: Callable[[GenerationTaskRequest], Awaitable[None]],
    settings: Settings | None = None,
) -> JobDispatcher:
    resolved_settings = settings or get_settings()
    if resolved_settings.workflow_dispatch_backend == "cloud_tasks":
        return CloudTasksJobDispatcher(settings=resolved_settings)

    return LocalJobDispatcher(runner=runner)
