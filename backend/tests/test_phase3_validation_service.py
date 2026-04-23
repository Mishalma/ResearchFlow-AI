from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from app.services.validation_service import (
    HttpValidationServiceClient,
    LocalValidationServiceClient,
)
from core.config import get_settings
from models.generation import GeneratedPaper, IEEESectionMap, ResearchPaperSchema
from models.job import WorkflowArtifactPointer
from models.validation import (
    ValidationReport,
    ValidationSectionReport,
    ValidationServiceRequest,
    ValidationServiceResponse,
)
from validation.runtime import execute_fast_validation


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _generated_paper() -> GeneratedPaper:
    return GeneratedPaper(
        paper=ResearchPaperSchema(
            title="Validation Test Title",
            abstract="This abstract is concise and original.",
            keywords=["validation", "workflow"],
            sections=IEEESectionMap(
                introduction=(
                    "The uploaded source document reported that adaptive tutoring improved assessment outcomes "
                    "across multiple districts using standardized pre-test and post-test comparisons."
                ),
                related_work="Related work summarizes prior tutoring systems.",
                methodology="We evaluate instructional interventions with consistent scoring criteria.",
                results="Results indicate measurable gains for the adaptive cohort.",
                discussion="The discussion interprets the observed gains.",
                limitations="The study is limited by sample diversity.",
                conclusion="The paper concludes with validation-ready findings.",
            ),
            references=["[1] Example reference"],
        ),
        formatted_text="Formatted manuscript body",
        latex_ready="\\documentclass{IEEEtran}",
    )


def _artifact_pointer(version: str, uri: str) -> WorkflowArtifactPointer:
    return WorkflowArtifactPointer(
        uri=uri,
        owner_service="validation-service",
        version=version,
        content_type="application/json",
        created_at=datetime.now(UTC),
        checksum_sha256=None,
    )


@pytest.mark.anyio
async def test_execute_fast_validation_returns_report_and_flags_overlap(monkeypatch):
    generated_paper = _generated_paper()
    source_text = (
        "Adaptive tutoring improved assessment outcomes across multiple districts using standardized "
        "pre-test and post-test comparisons. The original source also discussed instructional "
        "interventions and consistent scoring criteria."
    )

    monkeypatch.setattr("validation.runtime.load_generated_draft_artifact", lambda uri: generated_paper)
    monkeypatch.setattr("validation.runtime.load_extracted_text_artifact", lambda uri: source_text)
    monkeypatch.setattr(
        "validation.runtime.store_validation_report_artifact",
        lambda project_id, job_id, report, mode, revision="v1": _artifact_pointer(
            f"validation_{mode}_{revision}",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/metadata/validation_{mode}_{revision}.json",
        ),
    )

    class _PerplexityStub:
        def score(self, text: str):
            return None

    monkeypatch.setattr("validation.runtime._get_perplexity_scorer", lambda model_name: _PerplexityStub())

    response = await execute_fast_validation(
        ValidationServiceRequest(
            task_id="task-validation-1",
            job_id="job-123",
            project_id="project-123",
            user_id="user-123",
            idempotency_key="phase3-validation-123",
            current_draft_uri="gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v1.json",
            artifacts={"extracted_text_uri": "gs://bucket/projects/project-123/jobs/job-123/sources/extracted_text.json"},
            config={"mode": "fast", "changed_sections_only": False},
        )
    )

    assert response.output.mode == "fast"
    assert response.output.validation_report_uri.endswith("validation_fast_v1.json")
    assert response.output.report.routing_decision in {"borderline", "flagged"}
    assert response.output.report.plagiarism_score > 0
    assert any(flag.flag_type == "plagiarism" for flag in response.output.section_flags)


@pytest.mark.anyio
async def test_local_validation_service_client_runs_without_http(monkeypatch):
    expected = {
        "job_id": "job-123",
        "status": "VALIDATING",
        "stage": "validation",
        "output": {
            "mode": "fast",
            "ai_score": 0.1,
            "plagiarism_score": 2.0,
            "confidence_band": "low",
            "routing_decision": "clean",
            "section_flags": [],
            "validation_report_uri": "gs://bucket/projects/project-123/jobs/job-123/metadata/validation_fast_v1.json",
            "report": {
                "ai_score": 0.1,
                "plagiarism_score": 2.0,
                "confidence_band": "low",
                "routing_decision": "clean",
                "deep_validation_used": False,
                "sections": [],
                "decision_summary": "Validation complete.",
            },
        },
    }

    async def fake_execute(request, *, settings=None):
        assert request.job_id == "job-123"
        return ValidationServiceResponse.model_validate(expected)

    monkeypatch.setattr("app.services.validation_service.execute_validation_request", fake_execute)

    client = LocalValidationServiceClient(settings=get_settings())
    response = await client.run_validation(
        ValidationServiceRequest(
            task_id="task-123",
            job_id="job-123",
            project_id="project-123",
            user_id="user-123",
            idempotency_key="phase3-validation-123",
            current_draft_uri="gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v1.json",
            artifacts={"extracted_text_uri": "gs://bucket/projects/project-123/jobs/job-123/sources/extracted_text.json"},
        )
    )

    assert response.job_id == "job-123"
    assert response.output.routing_decision == "clean"


@pytest.mark.anyio
async def test_http_validation_service_client_serializes_and_deserializes():
    settings = replace(
        get_settings(),
        workflow_validation_backend="service",
        validation_service_base_url="https://validation.internal.run.app",
        validation_service_audience="https://validation.internal.run.app",
        validation_service_timeout_seconds=120,
    )

    async def fake_auth_provider(audience: str) -> str | None:
        assert audience == "https://validation.internal.run.app"
        return "test-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://validation.internal.run.app/internal/validation/run"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["job_id"] == "job-456"
        assert payload["current_draft_uri"].endswith("draft_v1.json")
        return httpx.Response(
            status_code=200,
            json={
                "job_id": "job-456",
                "status": "VALIDATING",
                "stage": "validation",
                "output": {
                    "mode": "fast",
                    "ai_score": 0.27,
                    "plagiarism_score": 6.4,
                    "confidence_band": "medium",
                    "routing_decision": "borderline",
                    "section_flags": [
                        {
                            "section_id": "introduction",
                            "flag_type": "ai",
                            "score": 0.27,
                            "risk": "medium",
                            "summary": "Introduction shows elevated AI-style signals.",
                        }
                    ],
                    "validation_report_uri": "gs://bucket/projects/project-456/jobs/job-456/metadata/validation_fast_v1.json",
                    "report": {
                        "ai_score": 0.27,
                        "plagiarism_score": 6.4,
                        "confidence_band": "medium",
                        "routing_decision": "borderline",
                        "deep_validation_used": False,
                        "sections": [],
                        "decision_summary": "Manual review suggested.",
                    },
                },
            },
        )

    client = HttpValidationServiceClient(
        settings=settings,
        transport=httpx.MockTransport(handler),
        auth_token_provider=fake_auth_provider,
    )

    response = await client.run_validation(
        ValidationServiceRequest(
            task_id="task-456",
            job_id="job-456",
            project_id="project-456",
            user_id="user-456",
            idempotency_key="phase3-validation-456",
            current_draft_uri="gs://bucket/projects/project-456/jobs/job-456/drafts/draft_v1.json",
            artifacts={"extracted_text_uri": "gs://bucket/projects/project-456/jobs/job-456/sources/extracted_text.json"},
        )
    )

    assert response.output.routing_decision == "borderline"
    assert response.output.validation_report_uri.endswith("validation_fast_v1.json")


@pytest.mark.anyio
async def test_execute_fast_validation_only_rescores_changed_sections(monkeypatch):
    generated_paper = _generated_paper()
    source_text = "This source text is only needed so validation can build its lexical index."
    previous_report = ValidationReport(
        ai_score=0.28,
        plagiarism_score=6.1,
        confidence_band="medium",
        routing_decision="borderline",
        deep_validation_used=False,
        sections=[
            ValidationSectionReport(
                section_name="abstract",
                ai_score=0.12,
                plagiarism_score=0.0,
                status="clean",
                risk="low",
                summary=["Abstract was clean in the previous pass."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="introduction",
                ai_score=0.34,
                plagiarism_score=7.5,
                status="needs_manual_review",
                risk="medium",
                summary=["Introduction required revalidation."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="related_work",
                ai_score=0.18,
                plagiarism_score=0.0,
                status="clean",
                risk="low",
                summary=["Related work stayed clean."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="methodology",
                ai_score=0.19,
                plagiarism_score=0.0,
                status="clean",
                risk="low",
                summary=["Methodology stayed clean."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="results",
                ai_score=0.29,
                plagiarism_score=0.0,
                status="needs_manual_review",
                risk="medium",
                summary=["Results still carry moderate AI-style risk."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="discussion",
                ai_score=0.17,
                plagiarism_score=0.0,
                status="clean",
                risk="low",
                summary=["Discussion stayed clean."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="limitations",
                ai_score=0.14,
                plagiarism_score=0.0,
                status="clean",
                risk="low",
                summary=["Limitations stayed clean."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="conclusion",
                ai_score=0.13,
                plagiarism_score=0.0,
                status="clean",
                risk="low",
                summary=["Conclusion stayed clean."],
                spans=[],
            ),
        ],
        decision_summary="Previous validation suggested manual review.",
    )

    rescored_sections: list[str] = []

    def fake_build_section_report(
        *,
        section_name: str,
        section_text: str,
        source_sentences,
        source_index,
        request: ValidationServiceRequest,
        validation_config,
        originality_config,
        reference_lines,
    ) -> ValidationSectionReport:
        rescored_sections.append(section_name)
        return ValidationSectionReport(
            section_name=section_name,
            ai_score=0.08,
            plagiarism_score=0.0,
            status="clean",
            risk="low",
            summary=["Introduction was rescored after the fix."],
            spans=[],
        )

    monkeypatch.setattr("validation.runtime.load_generated_draft_artifact", lambda uri: generated_paper)
    monkeypatch.setattr("validation.runtime.load_extracted_text_artifact", lambda uri: source_text)
    monkeypatch.setattr("validation.runtime.load_validation_report_from_artifact", lambda uri: previous_report)
    monkeypatch.setattr("validation.runtime._build_section_report", fake_build_section_report)
    monkeypatch.setattr(
        "validation.runtime.store_validation_report_artifact",
        lambda project_id, job_id, report, mode, revision="v1": _artifact_pointer(
            f"validation_{mode}_{revision}",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/metadata/validation_{mode}_{revision}.json",
        ),
    )

    class _PerplexityStub:
        def score(self, text: str):
            return None

    monkeypatch.setattr("validation.runtime._get_perplexity_scorer", lambda model_name: _PerplexityStub())

    response = await execute_fast_validation(
        ValidationServiceRequest(
            task_id="task-validation-recheck",
            job_id="job-456",
            project_id="project-456",
            user_id="user-456",
            idempotency_key="phase4-validation-456",
            current_draft_uri="gs://bucket/projects/project-456/jobs/job-456/drafts/draft_v2.json",
            artifacts={
                "extracted_text_uri": "gs://bucket/projects/project-456/jobs/job-456/sources/extracted_text.json",
                "previous_validation_report_uri": "gs://bucket/projects/project-456/jobs/job-456/metadata/validation_fast_v1.json",
            },
            config={
                "mode": "fast",
                "changed_sections_only": True,
                "changed_section_ids": ["introduction"],
            },
        )
    )

    assert rescored_sections == ["introduction"]
    assert response.output.validation_report_uri.endswith("validation_fast_v2.json")
    assert len(response.output.report.sections) == 8
    results_section = next(
        section for section in response.output.report.sections if section.section_name == "results"
    )
    introduction_section = next(
        section for section in response.output.report.sections if section.section_name == "introduction"
    )
    assert results_section.summary == ["Results still carry moderate AI-style risk."]
    assert introduction_section.summary == ["Introduction was rescored after the fix."]
    assert response.output.routing_decision == "borderline"
