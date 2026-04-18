from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.originality_agent import OriginalityAgent as PipelineOriginalityAgent
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import (
    GeneratedPaper,
    HumanizerAgentOutput,
    IEEESectionMap,
    OriginalityAgentOutput,
    ResearchPaperSchema,
)
from originality.agent import run_originality_pipeline
from originality.api_clients import ProviderClientError
from originality.config import OriginalityConfig
from originality.schemas import ProviderFinding, ProviderSectionScan


def _run(coro):
    return asyncio.run(coro)


def _build_generated_paper() -> GeneratedPaper:
    paper = ResearchPaperSchema(
        title="Traceable IEEE Workflow",
        abstract='The study states, "transformer models improved document screening" [1].',
        keywords=["workflow", "traceability"],
        sections=IEEESectionMap(
            introduction=(
                "Transformer models improved document screening in prior work. "
                "The workflow improves author review."
            ),
            related_work="Prior systems focused on fluency rather than provenance.",
            methodology="The pipeline processes the benchmark in three stages.",
            results="The workflow improved accuracy by 12% on the benchmark [1].",
            discussion="The evidence suggests the workflow may improve review quality.",
            limitations="The study is limited to one benchmark dataset.",
            conclusion="The workflow supports traceable IEEE drafting.",
        ),
        references=['[1] A. Author, "Traceable Workflow," IEEE Access, 2025.'],
    )
    return GeneratedPaper(paper=paper, formatted_text="formatted", latex_ready="latex")


class FakeWinstonClient:
    def __init__(self, section_finding: ProviderFinding | None = None):
        self.section_finding = section_finding

    async def scan_text(self, *, section_name: str, text: str, trace_id: str) -> ProviderSectionScan:
        findings = []
        if self.section_finding is not None and section_name == "abstract":
            findings = [
                self.section_finding.model_copy(
                    update={"metadata": {"provider_name": "winston_ai", "trace_id": trace_id}}
                )
            ]
        return ProviderSectionScan(
            provider_name="winston_ai",
            section_name=section_name,
            originality_score=0.94,
            spans=findings,
            metadata={"provider_summary": {"winston_ai": 1}},
        )


class ChunkedWinstonClient:
    async def scan_text(self, *, section_name: str, text: str, trace_id: str) -> ProviderSectionScan:
        return ProviderSectionScan(
            provider_name="winston_ai",
            section_name=section_name,
            originality_score=0.91,
            spans=[
                ProviderFinding(
                    start_char=0,
                    end_char=min(20, len(text)),
                    matched_text=text[: min(20, len(text))],
                    similarity_score=0.82,
                    severity=0.58,
                    metadata={"provider_name": "winston_ai", "trace_id": trace_id},
                )
            ],
        )


class FailingWinstonClient:
    async def scan_text(self, *, section_name: str, text: str, trace_id: str) -> ProviderSectionScan:
        raise ProviderClientError("Winston unavailable")


class FakeCopyleaksClient:
    async def scan_text(self, *, section_name: str, text: str, trace_id: str) -> ProviderSectionScan:
        return ProviderSectionScan(
            provider_name="copyleaks",
            section_name=section_name,
            originality_score=0.88,
            spans=[],
        )


class FailingCopyleaksClient:
    async def scan_text(self, *, section_name: str, text: str, trace_id: str) -> ProviderSectionScan:
        raise ProviderClientError("Copyleaks unavailable")


def test_missing_humanized_snapshot_returns_structured_error():
    result = _run(
        run_originality_pipeline(
            paper_snapshot=None,
            config=OriginalityConfig(),
        )
    )

    assert result.error is not None
    assert result.error.code == "missing_humanized_snapshot"
    assert result.approved_snapshot is None


def test_primary_provider_success_path_returns_approved_snapshot():
    finding = ProviderFinding(
        start_char=18,
        end_char=64,
        matched_text="transformer models improved document screening",
        similarity_score=0.42,
        matched_source_title="Traceable Workflow",
        matched_source_url="https://example.org/workflow",
        severity=0.38,
        metadata={"provider_name": "winston_ai"},
    )
    result = _run(
        run_originality_pipeline(
            paper_snapshot=_build_generated_paper(),
            config=OriginalityConfig(),
            winston_client=FakeWinstonClient(section_finding=finding),
            copyleaks_client=FakeCopyleaksClient(),
            trace_id="trace-originality",
        )
    )

    assert result.error is None
    assert result.approved_snapshot is not None
    assert result.originality_report is not None
    abstract_report = result.originality_report.sections["abstract"]
    assert abstract_report.spans[0].classification == "quoted_and_cited"
    assert result.originality_report.decision.graph_action == "accept"


def test_primary_failure_uses_copyleaks_fallback():
    result = _run(
        run_originality_pipeline(
            paper_snapshot=_build_generated_paper(),
            config=OriginalityConfig(provider_failure_retry_attempts=0),
            winston_client=FailingWinstonClient(),
            copyleaks_client=FakeCopyleaksClient(),
            trace_id="trace-fallback",
        )
    )

    assert result.error is None
    assert result.originality_report is not None
    assert result.metadata["provider_used"] == "copyleaks"


def test_both_providers_unavailable_routes_to_manual_review():
    result = _run(
        run_originality_pipeline(
            paper_snapshot=_build_generated_paper(),
            config=OriginalityConfig(provider_failure_retry_attempts=0),
            winston_client=FailingWinstonClient(),
            copyleaks_client=FailingCopyleaksClient(),
            trace_id="trace-manual-review",
        )
    )

    assert result.error is None
    assert result.approved_snapshot is not None
    assert result.originality_report is not None
    assert result.originality_report.decision.graph_action == "needs_manual_review"
    assert result.originality_report.decision.approved is True
    assert result.metadata["provider_review_pending"] is True


def test_chunked_section_scans_preserve_section_offsets():
    long_intro = " ".join(["Prior work improved tracing."] * 600)
    generated = _build_generated_paper()
    generated = generated.model_copy(
        update={
            "paper": generated.paper.model_copy(
                update={
                    "sections": generated.paper.sections.model_copy(
                        update={"introduction": long_intro}
                    )
                }
            )
        }
    )
    result = _run(
        run_originality_pipeline(
            paper_snapshot=generated,
            config=OriginalityConfig(section_chunk_chars=300, section_chunk_overlap_chars=40),
            winston_client=ChunkedWinstonClient(),
            copyleaks_client=FakeCopyleaksClient(),
            trace_id="trace-chunks",
        )
    )

    introduction_spans = result.originality_report.sections["introduction"].spans
    assert len(introduction_spans) >= 2
    assert introduction_spans[1].start_char > introduction_spans[0].start_char


def test_ai_score_can_trigger_retry_humanizer():
    result = _run(
        run_originality_pipeline(
            paper_snapshot=_build_generated_paper(),
            humanizer_ai_score=0.72,
            config=OriginalityConfig(retry_humanizer_ai_threshold=0.45),
            winston_client=FakeWinstonClient(),
            copyleaks_client=FakeCopyleaksClient(),
            trace_id="trace-retry-humanizer",
        )
    )

    assert result.approved_snapshot is None
    assert result.originality_report is not None
    assert result.originality_report.decision.graph_action == "retry_humanizer"


def test_compatibility_wrapper_returns_legacy_output(monkeypatch: pytest.MonkeyPatch):
    pipeline_result = _run(
        run_originality_pipeline(
            paper_snapshot=_build_generated_paper(),
            config=OriginalityConfig(),
            winston_client=FakeWinstonClient(),
            copyleaks_client=FakeCopyleaksClient(),
            trace_id="trace-wrapper",
        )
    )

    async def fake_run_originality_pipeline(**kwargs):
        return pipeline_result

    monkeypatch.setattr("agents.originality_agent.run_originality_pipeline", fake_run_originality_pipeline)

    spec = AgentSpec(
        name="originality_agent",
        role="test",
        input_schema="HumanizerAgentOutput",
        output_schema="OriginalityAgentOutput",
        model=None,
    )
    agent = PipelineOriginalityAgent(spec=spec)
    humanizer_output = HumanizerAgentOutput(
        paper=_build_generated_paper().paper,
        formatted_text="formatted",
        latex_ready="latex",
        humanized_draft=None,
        ai_pattern_score_after=0.2,
    )
    message = A2AMessage(
        sender="humanizer_agent",
        recipient="originality_agent",
        task="review_originality_and_compliance",
        trace_id="trace-wrapper",
        payload={"paper": humanizer_output.model_dump(mode="python")},
    )

    payload = _run(agent.process_task(message))
    output = OriginalityAgentOutput.model_validate(payload)

    assert output.originality_report is not None
    assert output.decision_graph_action == "accept"
