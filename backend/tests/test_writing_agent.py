from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.writing_agent import WritingAgent as PipelineWritingAgent
from core.exceptions import GenerationError
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import ResearchPaperSchema, WritingAgentOutput
from structuring.schemas import SectionSkeleton, SourceSpan, StructuredPaperDraft
from writing.agent import run_writing_pipeline
from writing.config import WritingConfig
from writing.schemas import BODY_WRITING_SECTIONS
from writing.section_writer import SectionGenerationResponse, TitleGenerationResponse
from writing.utils import annotate_section_text


def _run(coro):
    return asyncio.run(coro)


def _build_structured_draft(low_confidence: float = 0.82) -> StructuredPaperDraft:
    spans = [
        SourceSpan(
            chunk_id="chunk-0001",
            start_char=0,
            end_char=150,
            quote="The workflow improved section stability while preserving evidence links.",
            relevance_score=0.91,
        )
    ]
    sections = {
        "abstract": SectionSkeleton(
            section_name="abstract",
            draft="The paper describes an evidence-grounded IEEE drafting workflow with measurable stability benefits.",
            confidence=low_confidence,
            key_points=["The workflow improves drafting stability.", "Evidence links are preserved."],
            source_spans=spans,
            direct_evidence=["The workflow improves drafting stability while preserving evidence links."],
            inferred_synthesis=["The approach is suitable for structured academic writing pipelines."],
        ),
        "introduction": SectionSkeleton(
            section_name="introduction",
            draft="The introduction frames the need for secure, traceable drafting assistance in academic workflows.",
            confidence=0.84,
            key_points=["Secure drafting assistance is needed.", "Traceable evidence matters."],
            source_spans=spans,
            direct_evidence=["Secure academic drafting requires traceable evidence support."],
            inferred_synthesis=["A structured writing stage may reduce editorial friction."],
        ),
        "related_work": SectionSkeleton(
            section_name="related_work",
            draft="Prior authoring tools often optimize fluency but do not preserve provenance.",
            confidence=0.72,
            key_points=["Prior tools emphasize fluency.", "Provenance is often missing."],
            source_spans=spans,
            direct_evidence=["Many authoring tools optimize fluency without preserving provenance."],
            inferred_synthesis=["The current workflow differentiates itself through explicit evidence tracking."],
        ),
        "methodology": SectionSkeleton(
            section_name="methodology",
            draft="The methodology uses chunking, retrieval, evidence synthesis, and staged writing.",
            confidence=0.88,
            key_points=["Chunking is used.", "Retrieval is section-aware.", "Writing is staged."],
            source_spans=spans,
            direct_evidence=["The methodology uses chunking, retrieval, evidence synthesis, and staged writing."],
            inferred_synthesis=["The pipeline is designed for reproducible drafting."],
        ),
        "results": SectionSkeleton(
            section_name="results",
            draft="Results showed 95% section completion and 12% faster editorial turnaround.",
            confidence=0.9,
            key_points=["95% section completion.", "12% faster turnaround."],
            source_spans=spans,
            direct_evidence=["Results showed 95% section completion and 12% faster editorial turnaround."],
            inferred_synthesis=["The workflow can support efficient manuscript preparation."],
        ),
        "discussion": SectionSkeleton(
            section_name="discussion",
            draft="The discussion interprets the workflow as a balance between automation and author control.",
            confidence=0.63,
            key_points=["Automation is balanced with control."],
            source_spans=spans,
            direct_evidence=["The workflow balances automation with author control."],
            inferred_synthesis=["This balance may improve adoption in high-trust settings."],
        ),
        "limitations": SectionSkeleton(
            section_name="limitations",
            draft="The evidence is limited for highly domain-specific terminology and weak source documents.",
            confidence=low_confidence,
            key_points=["Domain-specific terminology remains challenging."],
            source_spans=spans,
            direct_evidence=["Highly domain-specific terminology remains challenging."],
            inferred_synthesis=["Performance may vary with weaker inputs."],
            missing_evidence=["Broader domain coverage data is limited."],
        ),
        "conclusion": SectionSkeleton(
            section_name="conclusion",
            draft="The conclusion synthesizes the contribution as an evidence-grounded writing workflow for IEEE papers.",
            confidence=0.8,
            key_points=["The workflow is evidence-grounded.", "It supports IEEE drafting."],
            source_spans=spans,
            direct_evidence=["The workflow supports evidence-grounded IEEE drafting."],
            inferred_synthesis=["The design is positioned for later citation and formatting stages."],
        ),
    }
    return StructuredPaperDraft(
        title_candidates=[
            "Evidence-Grounded IEEE Paper Generation Workflow",
            "Secure Academic Drafting Pipeline with Traceable Evidence",
        ],
        sections=sections,
        global_confidence=0.8,
        metadata={"trace_id": "trace-writing"},
    )


class StaticVertexClient:
    async def generate_json(self, *, prompt, response_schema, model_name=None):
        if response_schema is TitleGenerationResponse:
            return TitleGenerationResponse(title="Evidence-Grounded IEEE Paper Generation Workflow", revision_notes=["Selected model-backed title."])
        if response_schema is SectionGenerationResponse:
            return SectionGenerationResponse(
                text="The available evidence suggests the workflow improves drafting stability while preserving provenance controls.",
                revision_notes=["Generated with Vertex-backed section writer."],
            )
        raise AssertionError(f"Unexpected response schema: {response_schema}")


class FailingVertexClient:
    async def generate_json(self, *, prompt, response_schema, model_name=None):
        raise GenerationError("vertex unavailable")


class PartiallyFailingVertexClient:
    async def generate_json(self, *, prompt, response_schema, model_name=None):
        if response_schema is TitleGenerationResponse:
            return TitleGenerationResponse(title="Evidence-Grounded IEEE Paper Generation Workflow")
        if "discussion" in prompt.lower():
            raise GenerationError("discussion generation failed")
        return SectionGenerationResponse(
            text="The evidence suggests the workflow improves drafting stability while preserving provenance controls.",
            revision_notes=["Generated with Vertex-backed section writer."],
        )


def test_missing_structured_draft_returns_structured_error():
    result = _run(
        run_writing_pipeline(
            structured_draft=None,
            vertex_client=StaticVertexClient(),
            config=WritingConfig(use_model_generator=True),
        )
    )

    assert result.error is not None
    assert result.error.code == "missing_structured_draft"
    assert result.written_draft is None


def test_valid_normal_flow_generates_written_draft():
    result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            paper_topic="IEEE paper generation",
            paper_domain="academic workflow automation",
            vertex_client=StaticVertexClient(),
            config=WritingConfig(use_model_generator=True, enable_diversity_pass=True),
        )
    )

    assert result.error is None
    assert result.written_draft is not None
    assert result.paper_snapshot is not None
    assert result.written_draft.title
    assert result.written_draft.abstract.text
    for section_name in BODY_WRITING_SECTIONS:
        assert section_name in result.written_draft.sections
        assert result.written_draft.sections[section_name].text


def test_confidence_bounds_preserved():
    result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            vertex_client=StaticVertexClient(),
            config=WritingConfig(use_model_generator=True),
        )
    )

    assert result.written_draft is not None
    assert 0.0 <= result.written_draft.global_confidence <= 1.0
    assert 0.0 <= result.written_draft.abstract.confidence <= 1.0
    for section in result.written_draft.sections.values():
        assert 0.0 <= section.confidence <= 1.0


def test_title_generation_prefers_candidates():
    result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            vertex_client=StaticVertexClient(),
            config=WritingConfig(use_model_generator=True),
        )
    )

    assert result.written_draft is not None
    assert result.written_draft.title == "Evidence-Grounded IEEE Paper Generation Workflow"


def test_deterministic_fallback_generation_is_real_runtime_path():
    result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            vertex_client=FailingVertexClient(),
            config=WritingConfig(use_model_generator=True, enable_diversity_pass=False),
        )
    )

    assert result.error is None
    assert result.written_draft is not None
    assert result.written_draft.sections["methodology"].revision_notes
    assert any("deterministic fallback" in note.lower() or "deterministic" in note.lower() for note in result.written_draft.sections["methodology"].revision_notes)


def test_diversity_pass_does_not_change_numeric_facts():
    result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            vertex_client=FailingVertexClient(),
            config=WritingConfig(use_model_generator=True, enable_diversity_pass=True),
        )
    )

    assert result.written_draft is not None
    results_text = result.written_draft.sections["results"].text
    assert "95%" in results_text
    assert "12%" in results_text


def test_hedging_preserved_for_low_confidence_sections():
    low_draft = _build_structured_draft(low_confidence=0.32)
    result = _run(
        run_writing_pipeline(
            structured_draft=low_draft,
            vertex_client=FailingVertexClient(),
            config=WritingConfig(use_model_generator=True, enable_diversity_pass=True),
        )
    )

    assert result.written_draft is not None
    limitations = result.written_draft.sections["limitations"]
    assert limitations.hedged_sentences


def test_unsupported_sentence_detection_logic():
    skeleton = _build_structured_draft().sections["results"]
    bundle = annotate_section_text(
        text="The system proves a universal improvement across all domains.",
        section_name="results",
        confidence=0.9,
        skeleton=SectionSkeleton(
            section_name="results",
            draft="",
            confidence=0.9,
            key_points=[],
            source_spans=[],
            direct_evidence=[],
            inferred_synthesis=[],
        ),
    )

    assert bundle.unsupported_sentences == ["The system proves a universal improvement across all domains."]


def test_graceful_fallback_when_one_section_is_malformed():
    result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            vertex_client=PartiallyFailingVertexClient(),
            config=WritingConfig(use_model_generator=True, enable_diversity_pass=False),
        )
    )

    assert result.written_draft is not None
    discussion = result.written_draft.sections["discussion"]
    assert discussion.text
    assert any("fallback" in note.lower() for note in discussion.revision_notes)


def test_compatibility_wrapper_returns_legacy_snapshot(monkeypatch: pytest.MonkeyPatch):
    pipeline_result = _run(
        run_writing_pipeline(
            structured_draft=_build_structured_draft(),
            vertex_client=StaticVertexClient(),
            config=WritingConfig(use_model_generator=True),
            fallback_keywords=["academic drafting", "evidence"],
        )
    )

    async def fake_run_writing_pipeline(**kwargs):
        return pipeline_result

    monkeypatch.setattr("agents.writing_agent.run_writing_pipeline", fake_run_writing_pipeline)

    spec = AgentSpec(
        name="writing_agent",
        role="test",
        input_schema="ResearchPaperSchema",
        output_schema="WritingAgentOutput",
        model="gemini-2.5-flash",
    )
    agent = PipelineWritingAgent(client=StaticVertexClient(), spec=spec)
    legacy_paper = ResearchPaperSchema(
        title="Legacy Title",
        abstract="Legacy abstract",
        keywords=["academic drafting", "evidence"],
        sections=pipeline_result.paper_snapshot.sections,
        references=[],
    )
    message = A2AMessage(
        sender="structuring_agent",
        recipient="writing_agent",
        task="improve_sections",
        trace_id="trace-writing",
        payload={"paper": {**legacy_paper.model_dump(mode="python"), "structured_draft": _build_structured_draft().model_dump(mode="python")}},
    )

    payload = _run(agent.process_task(message))
    writing_output = WritingAgentOutput.model_validate(payload)
    paper_snapshot = ResearchPaperSchema.model_validate(payload)

    assert writing_output.written_draft is not None
    assert paper_snapshot.sections.limitations
    assert paper_snapshot.keywords == ["academic drafting", "evidence"]
