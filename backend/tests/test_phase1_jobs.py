from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.auth import AuthenticatedRequestUser
from jobs.service import create_generation_job, get_job_status, run_generation_task
from models.generation import (
    AgentTiming,
    GeneratedPaper,
    GenerationServiceResponse,
    GenerationMetadata,
    IEEESectionMap,
    ResearchPaperSchema,
)
from models.job import GenerationTaskRequest, JobRecord
from models.job import WorkflowArtifactPointer
from models.project import ProjectRecord


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class InMemoryJobRepository:
    def __init__(self):
        self.jobs: dict[str, JobRecord] = {}
        self.save_history: list[tuple[str, str]] = []

    def save(self, job: JobRecord) -> JobRecord:
        self.jobs[job.job_id] = job
        self.save_history.append((job.status, job.stage))
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)

    def find_by_idempotency(self, *, user_id: str, project_id: str, idempotency_key: str) -> JobRecord | None:
        for job in self.jobs.values():
            if (
                job.user_id == user_id
                and job.project_id == project_id
                and job.idempotency_key == idempotency_key
            ):
                return job
        return None

    def find_active_by_user(self, user_id: str) -> JobRecord | None:
        for job in self.jobs.values():
            if job.user_id == user_id and job.status in {"CREATED", "GENERATION_REQUESTED", "GENERATING"}:
                return job
        return None


def _make_user() -> AuthenticatedRequestUser:
    return AuthenticatedRequestUser(
        user_id="user-123",
        email="user@example.com",
        display_name="User Example",
    )


def _make_project() -> ProjectRecord:
    return ProjectRecord(
        id="project-123",
        file_name="source.docx",
        file_path="",
        extracted_text="Source text for generation",
        file_type="docx",
        file_size=123,
        extraction_time_ms=12.5,
        title="Source Project",
        owner_uid="user-123",
        owner_email="user@example.com",
    )


def _make_generated_paper() -> GeneratedPaper:
    return GeneratedPaper(
        paper=ResearchPaperSchema(
            title="Generated Title",
            abstract="Generated abstract",
            keywords=["ai"],
            sections=IEEESectionMap(
                introduction="Intro",
                related_work="Related",
                methodology="Method",
                results="Results",
                discussion="Discussion",
                limitations="Limitations",
                conclusion="Conclusion",
            ),
            references=["[1] Example"],
        ),
        formatted_text="Generated formatted text",
        latex_ready="Generated latex",
    )


def _make_generation_metadata() -> GenerationMetadata:
    return GenerationMetadata(
        model="gemini-test",
        generation_time_ms=1234,
        source_text_length=256,
        trace_id="trace-123",
        agent_timings=[AgentTiming(agent="writing_agent", duration_ms=50)],
        originality_global_ai_score=0.12,
        originality_global_score=0.88,
    )


def _artifact_pointer(version: str, uri: str) -> WorkflowArtifactPointer:
    return WorkflowArtifactPointer(
        uri=uri,
        owner_service="phase1-monolith",
        version=version,
        content_type="application/json",
        created_at=datetime.now(UTC),
        checksum_sha256=None,
    )


def test_in_memory_job_repository_round_trip():
    repository = InMemoryJobRepository()
    job = JobRecord(
        job_id="job-123",
        project_id="project-123",
        user_id="user-123",
        idempotency_key="phase1-project-123",
    )

    repository.save(job)

    loaded = repository.get("job-123")
    assert loaded is not None
    assert loaded.job_id == "job-123"
    assert repository.find_by_idempotency(
        user_id="user-123",
        project_id="project-123",
        idempotency_key="phase1-project-123",
    ) is not None
    assert repository.find_active_by_user("user-123") is not None


def test_create_generation_job_is_idempotent(monkeypatch):
    repository = InMemoryJobRepository()
    project = _make_project()

    monkeypatch.setattr("jobs.service.get_job_repository", lambda: repository)
    monkeypatch.setattr("jobs.service.get_project", lambda project_id, owner_uid: project)
    monkeypatch.setattr(
        "jobs.service.store_extracted_text_artifact",
        lambda project_id, job_id, extracted_text: _artifact_pointer(
            "extracted_text",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/sources/extracted_text.json",
        ),
    )

    first_job, created_first = create_generation_job(
        project_id=project.id,
        current_user=_make_user(),
        idempotency_key="phase1-project-123",
    )
    second_job, created_second = create_generation_job(
        project_id=project.id,
        current_user=_make_user(),
        idempotency_key="phase1-project-123",
    )

    assert created_first is True
    assert created_second is False
    assert first_job.job_id == second_job.job_id
    assert first_job.artifacts.extracted_text is not None


@pytest.mark.anyio
async def test_run_generation_task_success_transitions_to_done(monkeypatch):
    repository = InMemoryJobRepository()
    project = _make_project()
    job = JobRecord(
        job_id="job-123",
        project_id=project.id,
        user_id=project.owner_uid,
        idempotency_key="phase1-project-123",
        status="GENERATION_REQUESTED",
    )
    repository.save(job)

    generated_paper = _make_generated_paper()
    metadata = _make_generation_metadata()

    monkeypatch.setattr("jobs.service.get_job_repository", lambda: repository)
    monkeypatch.setattr("jobs.service.get_project", lambda project_id, owner_uid: project)

    calls: list[GenerationTaskRequest | GenerationServiceResponse] = []

    class FakeGenerationClient:
        async def run_generation(self, request):
            calls.append(request)
            assert request.source_text == project.extracted_text
            assert request.project_id == project.id
            return GenerationServiceResponse(
                job_id=request.job_id,
                project_id=request.project_id,
                generated_paper=generated_paper,
                metadata=metadata,
                generated_figures=None,
                generated_tables=None,
                figure_table_status="skipped",
                figure_table_error=None,
                boundary="formatting_complete",
            )

    monkeypatch.setattr("jobs.service.get_generation_service_client", lambda: FakeGenerationClient())

    def fake_save_generated_paper(**kwargs):
        return project.model_copy(
            update={
                "generated_paper": generated_paper,
                "generation_metadata": metadata,
                "display_paper_text": generated_paper.formatted_text,
                "latex_ready": generated_paper.latex_ready,
            }
        )

    monkeypatch.setattr("jobs.service.save_generated_paper", fake_save_generated_paper)
    monkeypatch.setattr(
        "jobs.service.store_generated_draft_artifact",
        lambda project_id, job_id, version, generated_paper: _artifact_pointer(
            version,
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/drafts/{version}.json",
        ),
    )
    monkeypatch.setattr(
        "jobs.service.store_final_accepted_draft_artifact",
        lambda project_id, job_id, generated_paper: _artifact_pointer(
            "final_accepted_draft",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/reports/final_accepted_draft.json",
        ),
    )
    monkeypatch.setattr(
        "jobs.service.store_job_result_report",
        lambda project_id, job_id, result: _artifact_pointer(
            "final_report",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/reports/final_report.json",
        ),
    )

    class _Storage:
        def get_uri(self, key: str) -> str:
            return f"gs://bucket/{key}"

    monkeypatch.setattr("jobs.service.get_object_storage", lambda: _Storage())

    await run_generation_task(
        GenerationTaskRequest(
            task_id="task-123",
            job_id=job.job_id,
            project_id=project.id,
            user_id=project.owner_uid,
            idempotency_key=job.idempotency_key,
        )
    )

    saved = repository.get(job.job_id)
    assert saved is not None
    assert saved.status == "DONE"
    assert saved.stage == "done"
    assert saved.artifacts.draft_v1 is not None
    assert saved.artifacts.final_report is not None
    assert saved.scores.ai_score is None
    assert saved.scores.routing_decision == "pending"
    assert ("GENERATING", "generation") in repository.save_history
    assert ("GENERATED", "finalize") in repository.save_history
    assert calls
    status_response = get_job_status(job.job_id, project.owner_uid)
    assert status_response.progress.current_step == "complete"
    assert status_response.progress.percent == 100


@pytest.mark.anyio
async def test_run_generation_task_failure_transitions_to_failed(monkeypatch):
    repository = InMemoryJobRepository()
    project = _make_project()
    job = JobRecord(
        job_id="job-123",
        project_id=project.id,
        user_id=project.owner_uid,
        idempotency_key="phase1-project-123",
        status="GENERATION_REQUESTED",
    )
    repository.save(job)

    monkeypatch.setattr("jobs.service.get_job_repository", lambda: repository)
    monkeypatch.setattr("jobs.service.get_project", lambda project_id, owner_uid: project)

    class FailingGenerationClient:
        async def run_generation(self, request):
            raise RuntimeError("generation service exploded")

    monkeypatch.setattr("jobs.service.get_generation_service_client", lambda: FailingGenerationClient())

    await run_generation_task(
        GenerationTaskRequest(
            task_id="task-123",
            job_id=job.job_id,
            project_id=project.id,
            user_id=project.owner_uid,
            idempotency_key=job.idempotency_key,
        )
    )

    saved = repository.get(job.job_id)
    assert saved is not None
    assert saved.status == "FAILED"
    assert saved.error is not None
    assert saved.error.stage == "generation"
