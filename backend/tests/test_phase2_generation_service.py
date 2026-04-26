from __future__ import annotations

import json
from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace

import httpx
import pytest

from app.services.generation_service import (
    HttpGenerationServiceClient,
    LocalGenerationServiceClient,
)
from core.config import get_settings
from models.generation import (
    CitationAgentOutput,
    FormattingAgentOutput,
    GeneratedPaper,
    GenerationMetadata,
    GenerationServiceRequest,
    GenerationServiceResponse,
    IEEESectionMap,
    ResearchPaperSchema,
    StructuringAgentOutput,
    WritingAgentOutput,
)
from orchestration.pipeline import _FormattingPhaseResult, run_generation_pipeline


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _paper() -> ResearchPaperSchema:
    return ResearchPaperSchema(
        title="Formatting Boundary Title",
        abstract="Formatting boundary abstract",
        keywords=["ai", "workflow"],
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
    )


def _phase_result() -> _FormattingPhaseResult:
    paper = _paper()
    return _FormattingPhaseResult(
        resolved_settings=get_settings(),
        registry=SimpleNamespace(get=lambda _name: SimpleNamespace(enabled_tools=["semantic-scholar"])),
        vertex_client=object(),
        a2a_manager=object(),
        trace_id="trace-formatting",
        start_time=perf_counter() - 0.2,
        source_text_length=512,
        validation_events=["formatting_agent: validation passed on attempt 1"],
        pipeline_context={
            "generated_figure_count": 0,
            "generated_table_count": 0,
            "figure_table_status": "skipped",
            "figure_table_error": None,
        },
        structuring_agent=SimpleNamespace(agent_name="structuring_agent"),
        writing_agent=SimpleNamespace(agent_name="writing_agent"),
        figure_table_agent=SimpleNamespace(agent_name="figure_table_agent"),
        citation_agent=SimpleNamespace(agent_name="citation_agent"),
        formatting_agent=SimpleNamespace(agent_name="ieee_formatting_agent"),
        structuring_result=StructuringAgentOutput(
            **paper.model_dump(mode="python"),
            structured_draft={},
            global_confidence=0.91,
            section_confidences={"introduction": 0.9},
            evidence_summary={"introduction": 3},
        ),
        writing_result=WritingAgentOutput(
            **paper.model_dump(mode="python"),
            written_draft={},
            global_confidence=0.87,
            section_confidences={"introduction": 0.86},
            annotation_summary={"claims": 5},
        ),
        citation_result=CitationAgentOutput(
            **paper.model_dump(mode="python"),
            citation_draft={},
            matched_claim_count=5,
            bibliography_count=1,
            provider_summary={"semantic-scholar": 1},
        ),
        formatting_result=FormattingAgentOutput(
            paper=paper,
            formatted_text="Formatted output for the editor",
            latex_ready="\\\\documentclass{IEEEtran}",
            compile_success=True,
            retry_recommended=False,
            diagnostic_summary={"warnings": 0},
        ),
        structuring_duration_ms=10.0,
        writing_duration_ms=20.0,
        figure_table_duration_ms=5.0,
        citation_duration_ms=15.0,
        formatting_duration_ms=25.0,
    )


@pytest.mark.anyio
async def test_run_generation_pipeline_returns_formatting_output_without_humanizer(monkeypatch):
    async def fake_until_formatting(text: str, settings=None, *, project_id: str = ""):
        assert text == "source text"
        assert project_id == "project-123"
        return _phase_result()

    monkeypatch.setattr("orchestration.pipeline._run_pipeline_until_formatting", fake_until_formatting)
    monkeypatch.setattr(
        "orchestration.pipeline._execute_humanizer_loop",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("humanizer should not run")),
    )

    result = await run_generation_pipeline("source text", project_id="project-123")

    assert result.generated_paper.formatted_text == "Formatted output for the editor"
    assert result.generated_paper.paper.title == "Formatting Boundary Title"
    assert result.metadata.humanizer_graph_action is None
    assert result.metadata.originality_decision is None
    assert result.metadata.validation_events[-1] == (
        "pipeline: formatting boundary reached; humanizer/originality deferred"
    )
    assert result.remediation_context["trace_id"] == "trace-formatting"


@pytest.mark.anyio
async def test_execute_generation_request_passes_job_context_and_remediation_context(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_pipeline(text: str, settings=None, *, project_id: str = "", job_id: str = "", user_id: str = ""):
        captured["text"] = text
        captured["project_id"] = project_id
        captured["job_id"] = job_id
        captured["user_id"] = user_id
        return SimpleNamespace(
            generated_paper=GeneratedPaper(
                paper=_paper(),
                formatted_text="Formatted output for the editor",
                latex_ready="\\\\documentclass{IEEEtran}",
            ),
            metadata=GenerationMetadata(
                model="gemini-test",
                generation_time_ms=10,
                source_text_length=10,
                trace_id="trace-123",
            ),
            generated_figures=None,
            generated_tables=None,
            figure_table_status="skipped",
            figure_table_error=None,
            remediation_context={"trace_id": "trace-123", "sections": {"introduction": {"key_points": ["A"]}}},
        )

    monkeypatch.setattr("app.services.generation_service.run_generation_pipeline", fake_pipeline)

    from app.services.generation_service import execute_generation_request

    response = await execute_generation_request(
        GenerationServiceRequest(
            job_id="job-123",
            project_id="project-123",
            source_text="source text",
            user_id="user-123",
            idempotency_key="phase2-job-123",
        )
    )

    assert captured == {
        "text": "source text",
        "project_id": "project-123",
        "job_id": "job-123",
        "user_id": "user-123",
    }
    assert response.remediation_context["trace_id"] == "trace-123"


@pytest.mark.anyio
async def test_local_generation_service_client_runs_without_http(monkeypatch):
    phase_result = _phase_result()
    expected_response = GenerationServiceResponse(
        job_id="job-123",
        project_id="project-123",
        generated_paper=GeneratedPaper(
            paper=phase_result.formatting_result.paper,
            formatted_text=phase_result.formatting_result.formatted_text,
            latex_ready=phase_result.formatting_result.latex_ready,
        ),
        metadata=GenerationMetadata(
            model="gemini-test",
            generation_time_ms=10,
            source_text_length=10,
            trace_id="trace-123",
        ),
    )

    async def fake_execute(request, *, settings=None):
        assert request.job_id == "job-123"
        return expected_response

    monkeypatch.setattr("app.services.generation_service.execute_generation_request", fake_execute)

    client = LocalGenerationServiceClient(settings=get_settings())
    request = GenerationServiceRequest(
        job_id="job-123",
        project_id="project-123",
        source_text="source text",
        user_id="user-123",
        idempotency_key="phase2-job-123",
    )
    response = await client.run_generation(request)

    assert response.job_id == "job-123"
    assert response.metadata.trace_id == "trace-123"


@pytest.mark.anyio
async def test_http_generation_service_client_serializes_and_deserializes():
    settings = replace(
        get_settings(),
        workflow_generation_backend="service",
        generation_service_base_url="https://generation.internal.run.app",
        generation_service_audience="https://generation.internal.run.app",
        generation_service_timeout_seconds=1500,
    )
    paper = _paper()
    generated_paper = {
        "paper": paper.model_dump(mode="json"),
        "formatted_text": "Formatted output for the editor",
        "latex_ready": "\\\\documentclass{IEEEtran}",
    }

    async def fake_auth_provider(audience: str) -> str | None:
        assert audience == "https://generation.internal.run.app"
        return "test-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://generation.internal.run.app/internal/generation/run"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["job_id"] == "job-456"
        assert payload["project_id"] == "project-456"
        assert payload["source_text"] == "source text"
        return httpx.Response(
            status_code=200,
            json={
                "job_id": "job-456",
                "project_id": "project-456",
                "generated_paper": generated_paper,
                "metadata": {
                    "provider": "vertex_ai",
                    "model": "gemini-test",
                    "generation_time_ms": 111,
                    "source_text_length": 42,
                    "trace_id": "trace-456",
                    "agent_timings": [],
                    "mcp_tools_used": [],
                    "validation_events": ["pipeline: formatting boundary reached"],
                    "structuring_section_confidences": {},
                    "structuring_evidence_summary": {},
                    "writing_section_confidences": {},
                    "writing_annotation_summary": {},
                    "citation_provider_summary": {},
                    "formatting_diagnostic_summary": {},
                    "originality_section_status_counts": {},
                },
                "generated_figures": None,
                "generated_tables": None,
                "figure_table_status": "skipped",
                "figure_table_error": None,
                "boundary": "formatting_complete",
            },
        )

    client = HttpGenerationServiceClient(
        settings=settings,
        transport=httpx.MockTransport(handler),
        auth_token_provider=fake_auth_provider,
    )

    response = await client.run_generation(
        GenerationServiceRequest(
            job_id="job-456",
            project_id="project-456",
            source_text="source text",
            user_id="user-456",
            idempotency_key="phase2-job-456",
        )
    )

    assert response.boundary == "formatting_complete"
    assert response.generated_paper.paper.title == "Formatting Boundary Title"
    assert response.metadata.trace_id == "trace-456"
