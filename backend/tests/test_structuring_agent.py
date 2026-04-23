from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.structuring_agent import StructuringAgent as PipelineStructuringAgent
from core.config import get_settings
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import ResearchPaperSchema, StructuringAgentOutput
from structuring.agent import run_structuring_pipeline
from structuring.chunking import chunk_source_text
from structuring.config import StructuringConfig
from structuring.schemas import REQUIRED_STRUCTURING_SECTIONS
from structuring.summarizer import SectionReduceResponse


SAMPLE_SOURCE_TEXT = """
This study examines an AI-assisted research writing workflow for technical manuscripts.
The introduction explains the motivation for secure academic drafting, the need for traceable evidence,
and the objective of reducing repetitive editorial work while keeping authors in control.

Related work covers prior research on academic authoring tools, citation assistants, and automated
language support, noting that many systems optimize fluency without preserving provenance.

The methodology describes a multi-stage pipeline with document chunking, section-aware retrieval,
map-reduce evidence synthesis, and a downstream writing stage. The implementation uses structured
schemas, confidence scoring, and explicit evidence spans tied to chunk offsets.

Results indicate that the pipeline consistently produced section skeletons with grounded notes,
retrieval-based confidence estimates, and stable formatting-ready output. Evaluation emphasized
traceability, section completeness, and robustness when embeddings were unavailable.

The discussion interprets the workflow as a practical compromise between automation and editorial
control, with clear benefits for drafting speed and consistency. It also highlights the importance
of separating direct evidence from inferred synthesis in order to support later citation and writing steps.

Limitations include dependence on source quality, incomplete support for highly domain-specific terminology,
and the possibility that short or weak documents provide insufficient evidence for strong section drafts.

The conclusion summarizes the contribution as an evidence-grounded structuring stage for IEEE paper generation,
and suggests future work on richer scholarly retrieval, stronger citation linking, and improved reviewer-facing diagnostics.
""".strip()


class FailingEmbeddingProvider:
    backend_name = "failing-provider"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embeddings unavailable")


class StaticReducer:
    async def reduce_section(self, *, section_name: str, notes, context):
        evidence = [note.note for note in notes if note.note]
        direct = [item for note in notes for item in note.direct_evidence][:2]
        inferred = [f"Synthesized support for {section_name.replace('_', ' ')}."]
        missing = []
        return SectionReduceResponse(
            draft=" ".join(evidence[:2]) or f"{section_name} evidence requires review.",
            key_points=evidence[:3],
            direct_evidence=direct,
            inferred_synthesis=inferred,
            missing_evidence=missing,
        )

    async def suggest_titles(self, *, source_text: str, notes, context, limit: int) -> list[str]:
        return ["Evidence-Grounded IEEE Paper Structuring Workflow"][:limit]


class ExplodingReducer:
    async def reduce_section(self, *, section_name: str, notes, context):
        raise RuntimeError("reducer unavailable")

    async def suggest_titles(self, *, source_text: str, notes, context, limit: int) -> list[str]:
        raise RuntimeError("title reducer unavailable")


class ExplodingVertexClient:
    async def generate_json(self, *args, **kwargs):
        raise AssertionError("Vertex reducer should not be invoked in deterministic structuring mode")


def _run(coro):
    return asyncio.run(coro)


def test_empty_input_returns_structured_error():
    result = _run(
        run_structuring_pipeline(
            source_text="",
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    assert result.error is not None
    assert result.error.code == "empty_source_text"
    assert result.structured_draft is not None
    assert result.paper_snapshot is not None


def test_short_input_returns_structured_error():
    result = _run(
        run_structuring_pipeline(
            source_text="Brief note.",
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    assert result.error is not None
    assert result.error.code == "source_text_too_short"


def test_chunk_overlap_correctness():
    config = StructuringConfig(chunk_size_tokens=32, chunk_overlap_tokens=8)
    chunks = chunk_source_text(SAMPLE_SOURCE_TEXT * 3, config)

    assert len(chunks) >= 2
    assert chunks[0].start_char == 0
    assert chunks[1].start_char < chunks[0].end_char
    assert chunks[1].start_char >= chunks[0].end_char - config.chunk_overlap_chars - 50


def test_valid_section_output_for_normal_input():
    result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            paper_topic="AI-assisted academic drafting",
            paper_domain="research workflow automation",
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    assert result.error is None
    assert result.structured_draft is not None
    assert result.paper_snapshot is not None
    assert result.structured_draft.title_candidates
    for section_name in REQUIRED_STRUCTURING_SECTIONS:
        assert section_name in result.structured_draft.sections
        assert isinstance(result.structured_draft.sections[section_name].draft, str)
    assert result.paper_snapshot.sections.limitations


def test_confidence_bounds():
    result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    assert result.structured_draft is not None
    assert 0.0 <= result.structured_draft.global_confidence <= 1.0
    for section in result.structured_draft.sections.values():
        assert 0.0 <= section.confidence <= 1.0


def test_source_span_integrity():
    result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    assert result.structured_draft is not None
    for section in result.structured_draft.sections.values():
        for span in section.source_spans:
            assert span.chunk_id.startswith("chunk-")
            assert span.start_char <= span.end_char
            assert 0.0 <= (span.relevance_score or 0.0) <= 1.0


def test_fallback_retrieval_path_when_embeddings_fail():
    result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    assert result.structured_draft is not None
    assert result.structured_draft.metadata["retrieval_backend"] == "lexical"


def test_deterministic_reduction_fallback_when_reducer_fails():
    result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            embedding_provider=FailingEmbeddingProvider(),
            reducer=ExplodingReducer(),
        )
    )

    assert result.structured_draft is not None
    assert result.structured_draft.sections["methodology"].draft
    assert result.structured_draft.title_candidates


def test_structuring_defaults_to_deterministic_reduction_without_llm_reducer():
    result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            config=StructuringConfig(use_llm_reducer=False),
            vertex_client=ExplodingVertexClient(),
            embedding_provider=FailingEmbeddingProvider(),
        )
    )

    assert result.error is None
    assert result.structured_draft is not None
    assert result.metadata["reduction_backend"] == "deterministic"
    assert result.structured_draft.title_candidates


def test_compatibility_output_contains_pipeline_snapshot(monkeypatch: pytest.MonkeyPatch):
    pipeline_result = _run(
        run_structuring_pipeline(
            source_text=SAMPLE_SOURCE_TEXT,
            embedding_provider=FailingEmbeddingProvider(),
            reducer=StaticReducer(),
        )
    )

    async def fake_run_structuring_pipeline(**kwargs):
        return pipeline_result

    monkeypatch.setattr("agents.structuring_agent.run_structuring_pipeline", fake_run_structuring_pipeline)

    spec = AgentSpec(
        name="structuring_agent",
        role="test",
        input_schema="raw_text",
        output_schema="StructuringAgentOutput",
        model="gemini-2.5-flash",
    )
    agent = PipelineStructuringAgent(
        client=VertexGeminiClient(get_settings()),
        spec=spec,
        settings=get_settings(),
    )
    message = A2AMessage(
        sender="pipeline",
        recipient="structuring_agent",
        task="structure_document",
        trace_id="trace-test",
        payload={"raw_text": SAMPLE_SOURCE_TEXT},
    )

    payload = _run(agent.process_task(message))
    structured_output = StructuringAgentOutput.model_validate(payload)
    paper_snapshot = ResearchPaperSchema.model_validate(payload)

    assert structured_output.structured_draft is not None
    assert paper_snapshot.sections.limitations
