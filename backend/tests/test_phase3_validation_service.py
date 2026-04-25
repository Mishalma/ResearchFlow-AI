from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

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
from validation.config import ValidationConfig
from validation.desklib_detector import (
    DesklibDetectorError,
    DesklibPrediction,
    ensure_desklib_model_available,
)
from validation.runtime import _ai_score_for_section, execute_fast_validation


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


def test_desklib_detector_fails_fast_when_artifacts_are_missing():
    config = ValidationConfig(
        ai_detector_backend="desklib",
        ai_detector_model_path=Path("missing-desklib-snapshot-for-test"),
        ai_detector_model_gcs_uri="",
    )

    with pytest.raises(DesklibDetectorError):
        ensure_desklib_model_available(config)


def test_ai_score_for_section_uses_desklib_backend(monkeypatch):
    class _FakeDetector:
        def score_text(self, text: str) -> DesklibPrediction:
            assert "academic" in text.lower()
            return DesklibPrediction(
                score=0.0732,
                model_id="desklib/ai-text-detector-academic-v1.01",
                device="cuda",
                window_count=1,
                batch_size=8,
            )

    def fake_get_detector(config: ValidationConfig, *, project_id: str = "") -> _FakeDetector:
        assert config.ai_detector_backend == "desklib"
        return _FakeDetector()

    monkeypatch.setattr("validation.runtime.get_desklib_detector", fake_get_detector)

    score, metadata = _ai_score_for_section(
        "This academic section is being checked by the Desklib detector.",
        config=ValidationConfig(
            ai_detector_backend="desklib",
            ai_detector_model_path=Path("unused-desklib-snapshot-for-test"),
        ),
    )

    assert score == 0.0732
    assert metadata["ai_detector_backend"] == "desklib"
    assert metadata["ai_detector_model_id"] == "desklib/ai-text-detector-academic-v1.01"
    assert metadata["desklib_probability"] == 0.0732


@pytest.mark.anyio
async def test_execute_ai_check_flags_ai_without_overlap(monkeypatch):
    generated_paper = _generated_paper()

    monkeypatch.setattr("validation.runtime.load_generated_draft_artifact", lambda uri: generated_paper)
    monkeypatch.setattr(
        "validation.runtime.store_validation_report_artifact",
        lambda project_id, job_id, report, mode, revision="v1": _artifact_pointer(
            f"validation_{mode}_{revision}",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/metadata/validation_{mode}_{revision}.json",
        ),
    )
    monkeypatch.setattr(
        "validation.runtime._ai_score_for_section",
        lambda text, config: (0.22, {"desklib_probability": 0.22, "ai_detector_model_id": config.ai_detector_model_id}),
    )

    response = await execute_fast_validation(
        ValidationServiceRequest(
            task_id="task-validation-1",
            job_id="job-123",
            project_id="project-123",
            user_id="user-123",
            idempotency_key="phase3-validation-123",
            current_draft_uri="gs://bucket/projects/project-123/jobs/job-123/drafts/draft_v1.json",
            artifacts={},
            config={"mode": "ai_check", "changed_sections_only": False},
        )
    )

    assert response.output.mode == "ai_check"
    assert response.output.validation_report_uri.endswith("validation_ai_check_v1.json")
    assert response.output.report.routing_decision == "flagged"
    assert response.output.report.plagiarism_score == 0
    assert all(flag.flag_type == "ai" for flag in response.output.section_flags)


@pytest.mark.anyio
async def test_local_validation_service_client_runs_without_http(monkeypatch):
    expected = {
        "job_id": "job-123",
        "status": "VALIDATING",
        "stage": "validation",
        "output": {
            "mode": "ai_check",
            "ai_score": 0.1,
            "plagiarism_score": 2.0,
            "confidence_band": "low",
            "routing_decision": "accepted",
            "section_flags": [],
            "validation_report_uri": "gs://bucket/projects/project-123/jobs/job-123/metadata/validation_ai_check_v1.json",
            "report": {
                "ai_score": 0.1,
                "plagiarism_score": 2.0,
                "confidence_band": "low",
                "routing_decision": "accepted",
                "sections": [],
                "decision_summary": "Accepted.",
                "initial_ai_score": 0.1,
                "initial_plagiarism_score": 2.0,
                "final_ai_score": 0.1,
                "final_plagiarism_score": 2.0,
                "failure_reasons": [],
            },
            "failure_reasons": [],
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
    assert response.output.routing_decision == "accepted"


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
                    "mode": "ai_check",
                    "ai_score": 0.27,
                    "plagiarism_score": 6.4,
                    "confidence_band": "high",
                    "routing_decision": "flagged",
                    "section_flags": [
                        {
                            "section_id": "introduction",
                            "flag_type": "ai",
                            "score": 0.27,
                            "risk": "medium",
                            "summary": "Introduction shows elevated AI-style signals.",
                        }
                    ],
                    "validation_report_uri": "gs://bucket/projects/project-456/jobs/job-456/metadata/validation_ai_check_v1.json",
                    "report": {
                        "ai_score": 0.27,
                        "plagiarism_score": 6.4,
                        "confidence_band": "medium",
                        "routing_decision": "flagged",
                        "sections": [],
                        "decision_summary": "Flagged.",
                        "initial_ai_score": 0.27,
                        "initial_plagiarism_score": 6.4,
                        "final_ai_score": 0.27,
                        "final_plagiarism_score": 6.4,
                        "failure_reasons": ["ai_threshold_exceeded"],
                    },
                    "failure_reasons": ["ai_threshold_exceeded"],
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

    assert response.output.routing_decision == "flagged"
    assert response.output.validation_report_uri.endswith("validation_ai_check_v1.json")


@pytest.mark.anyio
async def test_execute_ai_check_only_rescores_changed_sections(monkeypatch):
    generated_paper = _generated_paper()
    previous_report = ValidationReport(
        ai_score=0.28,
        plagiarism_score=0.0,
        confidence_band="medium",
        routing_decision="flagged",
        sections=[
            ValidationSectionReport(
                section_name="abstract",
                ai_score=0.12,
                plagiarism_score=0.0,
                status="accepted",
                risk="low",
                summary=["Abstract stayed within threshold in the previous pass."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="introduction",
                ai_score=0.34,
                plagiarism_score=7.5,
                status="flagged",
                risk="medium",
                summary=["Introduction required revalidation."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="related_work",
                ai_score=0.18,
                plagiarism_score=0.0,
                status="accepted",
                risk="low",
                summary=["Related work stayed within threshold."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="methodology",
                ai_score=0.19,
                plagiarism_score=0.0,
                status="accepted",
                risk="low",
                summary=["Methodology stayed within threshold."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="results",
                ai_score=0.29,
                plagiarism_score=0.0,
                status="flagged",
                risk="medium",
                summary=["Results still carry moderate AI-style risk."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="discussion",
                ai_score=0.17,
                plagiarism_score=0.0,
                status="accepted",
                risk="low",
                summary=["Discussion stayed within threshold."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="limitations",
                ai_score=0.14,
                plagiarism_score=0.0,
                status="accepted",
                risk="low",
                summary=["Limitations stayed within threshold."],
                spans=[],
            ),
            ValidationSectionReport(
                section_name="conclusion",
                ai_score=0.13,
                plagiarism_score=0.0,
                status="accepted",
                risk="low",
                summary=["Conclusion stayed within threshold."],
                spans=[],
            ),
        ],
        decision_summary="Previous validation flagged the draft.",
        initial_ai_score=0.28,
        initial_plagiarism_score=0.0,
        final_ai_score=0.28,
        final_plagiarism_score=0.0,
        failure_reasons=["ai_threshold_exceeded"],
    )

    rescored_sections: list[str] = []

    def fake_build_section_report(*, section_name: str, section_text: str, validation_config) -> ValidationSectionReport:
        rescored_sections.append(section_name)
        return ValidationSectionReport(
            section_name=section_name,
            ai_score=0.08,
            plagiarism_score=0.0,
            status="accepted",
            risk="low",
            summary=["Introduction was rescored after the fix."],
            spans=[],
        )

    monkeypatch.setattr("validation.runtime.load_generated_draft_artifact", lambda uri: generated_paper)
    monkeypatch.setattr("validation.runtime.load_validation_report_from_artifact", lambda uri: previous_report)
    monkeypatch.setattr("validation.runtime._build_ai_only_section_report", fake_build_section_report)
    monkeypatch.setattr(
        "validation.runtime.store_validation_report_artifact",
        lambda project_id, job_id, report, mode, revision="v1": _artifact_pointer(
            f"validation_{mode}_{revision}",
            f"gs://bucket/projects/{project_id}/jobs/{job_id}/metadata/validation_{mode}_{revision}.json",
        ),
    )

    response = await execute_fast_validation(
        ValidationServiceRequest(
            task_id="task-validation-recheck",
            job_id="job-456",
            project_id="project-456",
            user_id="user-456",
            idempotency_key="phase4-validation-456",
            current_draft_uri="gs://bucket/projects/project-456/jobs/job-456/drafts/draft_v2.json",
            artifacts={
                "previous_validation_report_uri": "gs://bucket/projects/project-456/jobs/job-456/metadata/validation_ai_check_v1.json",
            },
            config={
                "mode": "ai_check",
                "changed_sections_only": True,
                "changed_section_ids": ["introduction"],
            },
        )
    )

    assert rescored_sections == ["introduction"]
    assert response.output.validation_report_uri.endswith("validation_ai_check_v2.json")
    assert len(response.output.report.sections) == 8
    results_section = next(
        section for section in response.output.report.sections if section.section_name == "results"
    )
    introduction_section = next(
        section for section in response.output.report.sections if section.section_name == "introduction"
    )
    assert results_section.summary == ["Results still carry moderate AI-style risk."]
    assert introduction_section.summary == ["Introduction was rescored after the fix."]
    assert response.output.routing_decision == "flagged"
