from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from app.services.fix_service import HttpFixServiceClient, LocalFixServiceClient
from core.config import get_settings
from fix.runtime import execute_fix_request
from models.fix import FixServiceRequest, FixServiceResponse, FixSectionTarget
from models.generation import GeneratedPaper, IEEESectionMap, ResearchPaperSchema
from models.job import WorkflowArtifactPointer


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _generated_paper() -> GeneratedPaper:
    return GeneratedPaper(
        paper=ResearchPaperSchema(
            title="Fix Test Title",
            abstract="This abstract is already acceptable.",
            keywords=["ai", "fix"],
            sections=IEEESectionMap(
                introduction=(
                    "Furthermore, it is important to note that the results demonstrate a 12% "
                    "improvement in accuracy [1] across the benchmark. Additionally, the analysis "
                    "highlights consistent behavior across the benchmark, and \\cite{smith2024} "
                    "confirms the same trend in a comparable setting."
                ),
                related_work="Related work stays untouched in this test.",
                methodology="The methodology section remains unchanged.",
                results="The results are summarized plainly.",
                discussion="The discussion remains stable.",
                limitations="The limitations remain explicit.",
                conclusion="The conclusion closes the paper cleanly.",
            ),
            references=["[1] Example reference"],
        ),
        formatted_text="Formatted manuscript body",
        latex_ready="\\documentclass{IEEEtran}",
    )


def _artifact_pointer(version: str, uri: str) -> WorkflowArtifactPointer:
    return WorkflowArtifactPointer(
        uri=uri,
        owner_service="fix-service",
        version=version,
        content_type="application/json",
        created_at=datetime.now(UTC),
        checksum_sha256=None,
    )


@pytest.mark.anyio
async def test_execute_fix_request_rewrites_only_targeted_sections_and_preserves_protected_tokens(monkeypatch):
    generated_paper = _generated_paper()
    stored: dict[str, GeneratedPaper] = {}
    monkeypatch.setenv("HUMANIZER_SEMANTIC_DRIFT_THRESHOLD", "1.0")

    monkeypatch.setattr("fix.runtime.load_generated_draft_artifact", lambda uri: generated_paper)
    monkeypatch.setattr(
        "fix.runtime.store_generated_draft_artifact",
        lambda project_id, job_id, version, generated_paper, owner_service="fix-service": (
            stored.setdefault("draft", generated_paper),
            _artifact_pointer(
                version,
                f"gs://bucket/projects/{project_id}/jobs/{job_id}/drafts/{version}.json",
            ),
        )[1],
    )

    response = await execute_fix_request(
        FixServiceRequest(
            task_id="fix-task-123",
            job_id="job-123",
            project_id="project-123",
            user_id="user-123",
            idempotency_key="phase4-fix-123",
            current_draft_uri="gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v1.json",
            validation_report_uri="gs://bucket/projects/project-123/jobs/job-123/metadata/validation_fast_v1.json",
            iteration=1,
            mode="ai_style",
            targets=[
                FixSectionTarget(
                    section_id="introduction",
                    score=0.31,
                    risk="medium",
                    summary="Introduction shows elevated AI-style signals.",
                )
            ],
        )
    )

    assert response.output.fix_status == "applied"
    assert response.output.changed_sections == ["introduction"]
    assert response.output.updated_draft_uri.endswith("draft_v2.json")
    assert response.output.rewriter_mode == "deterministic"

    updated_draft = stored["draft"]
    updated_intro = updated_draft.paper.sections.introduction
    assert updated_intro != generated_paper.paper.sections.introduction
    assert "[1]" in updated_intro
    assert "12%" in updated_intro
    assert "\\cite{smith2024}" in updated_intro
    assert (
        updated_draft.paper.sections.related_work
        == generated_paper.paper.sections.related_work
    )


@pytest.mark.anyio
async def test_execute_fix_request_without_targets_returns_not_needed(monkeypatch):
    generated_paper = _generated_paper()

    monkeypatch.setattr("fix.runtime.load_generated_draft_artifact", lambda uri: generated_paper)
    monkeypatch.setattr(
        "fix.runtime.load_validation_report_artifact",
        lambda uri: {"section_flags": []},
    )
    monkeypatch.setattr(
        "fix.runtime.store_generated_draft_artifact",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("draft should not be stored")),
    )

    response = await execute_fix_request(
        FixServiceRequest(
            task_id="fix-task-456",
            job_id="job-456",
            project_id="project-456",
            user_id="user-456",
            idempotency_key="phase4-fix-456",
            current_draft_uri="gs://bucket/projects/project-456/jobs/job-456/drafts/draft_v1.json",
            validation_report_uri="gs://bucket/projects/project-456/jobs/job-456/metadata/validation_fast_v1.json",
            iteration=1,
            mode="ai_style",
        )
    )

    assert response.output.fix_status == "not_needed"
    assert response.output.changed_sections == []
    assert response.output.draft_artifact is None
    assert response.output.updated_draft_uri.endswith("draft_v1.json")


@pytest.mark.anyio
async def test_local_fix_service_client_runs_without_http(monkeypatch):
    expected = {
        "job_id": "job-123",
        "status": "FIXING",
        "stage": "fix",
        "output": {
            "mode": "ai_style",
            "updated_draft_uri": "gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v2.json",
            "draft_artifact": {
                "uri": "gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v2.json",
                "owner_service": "fix-service",
                "version": "draft_v2",
                "content_type": "application/json",
                "created_at": datetime.now(UTC).isoformat(),
                "checksum_sha256": None,
            },
            "changed_sections": ["introduction"],
            "rewriter_mode": "deterministic",
            "fix_status": "applied",
            "fix_summary": {
                "attempted": True,
                "status": "applied",
                "iterations": 1,
                "changed_sections": ["introduction"],
                "rewriter_mode": "deterministic",
            },
        },
    }

    async def fake_execute(request, *, settings=None):
        assert request.job_id == "job-123"
        return FixServiceResponse.model_validate(expected)

    monkeypatch.setattr("app.services.fix_service.execute_fix_service_request", fake_execute)

    client = LocalFixServiceClient(settings=get_settings())
    response = await client.run_fix(
        FixServiceRequest(
            task_id="fix-task-123",
            job_id="job-123",
            project_id="project-123",
            user_id="user-123",
            idempotency_key="phase4-fix-123",
            current_draft_uri="gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v1.json",
            validation_report_uri="gs://bucket/projects/project-123/jobs/job-123/metadata/validation_fast_v1.json",
            iteration=1,
        )
    )

    assert response.output.fix_status == "applied"
    assert response.output.changed_sections == ["introduction"]


@pytest.mark.anyio
async def test_http_fix_service_client_serializes_and_deserializes():
    settings = replace(
        get_settings(),
        workflow_fix_backend="service",
        fix_service_base_url="https://fix.internal.run.app",
        fix_service_audience="https://fix.internal.run.app",
        fix_service_timeout_seconds=180,
    )

    async def fake_auth_provider(audience: str) -> str | None:
        assert audience == "https://fix.internal.run.app"
        return "test-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://fix.internal.run.app/internal/fix/run"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["job_id"] == "job-789"
        assert payload["current_draft_uri"].endswith("draft_v1.json")
        return httpx.Response(
            status_code=200,
            json={
                "job_id": "job-789",
                "status": "FIXING",
                "stage": "fix",
                "output": {
                    "mode": "ai_style",
                    "updated_draft_uri": "gs://bucket/projects/project-789/jobs/job-789/drafts/draft_v2.json",
                    "draft_artifact": {
                        "uri": "gs://bucket/projects/project-789/jobs/job-789/drafts/draft_v2.json",
                        "owner_service": "fix-service",
                        "version": "draft_v2",
                        "content_type": "application/json",
                        "created_at": datetime.now(UTC).isoformat(),
                        "checksum_sha256": None,
                    },
                    "changed_sections": ["discussion"],
                    "rewriter_mode": "deterministic",
                    "fix_status": "applied",
                    "fix_summary": {
                        "attempted": True,
                        "status": "applied",
                        "iterations": 2,
                        "changed_sections": ["discussion"],
                        "rewriter_mode": "deterministic",
                    },
                },
            },
        )

    client = HttpFixServiceClient(
        settings=settings,
        transport=httpx.MockTransport(handler),
        auth_token_provider=fake_auth_provider,
    )

    response = await client.run_fix(
        FixServiceRequest(
            task_id="fix-task-789",
            job_id="job-789",
            project_id="project-789",
            user_id="user-789",
            idempotency_key="phase4-fix-789",
            current_draft_uri="gs://bucket/projects/project-789/jobs/job-789/drafts/draft_v1.json",
            validation_report_uri="gs://bucket/projects/project-789/jobs/job-789/metadata/validation_fast_v1.json",
            iteration=2,
            targets=[
                FixSectionTarget(
                    section_id="discussion",
                    score=0.29,
                    risk="medium",
                    summary="Discussion is still a little too formulaic.",
                )
            ],
        )
    )

    assert response.output.fix_status == "applied"
    assert response.output.changed_sections == ["discussion"]
