from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.citation_agent import CitationAgent as PipelineCitationAgent
from citation.agent import run_citation_pipeline
from citation.config import CitationConfig
from citation.schemas import ProviderCandidate
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import CitationAgentOutput, ResearchPaperSchema
from structuring.schemas import SectionSkeleton, SourceSpan, StructuredPaperDraft
from writing.schemas import WrittenClaim, WrittenPaperDraft, WrittenSection


def _run(coro):
    return asyncio.run(coro)


def _build_written_draft() -> WrittenPaperDraft:
    shared_span = {
        "span_id": "chunk-001:0:120",
        "chunk_id": "chunk-001",
        "start_char": 0,
        "end_char": 120,
        "quote": "Transformers improved biomedical text classification.",
        "relevance_score": 0.91,
    }
    abstract = WrittenSection(
        section_name="abstract",
        text="Prior transformer studies suggest improved biomedical text classification.",
        confidence=0.84,
        claims=[
            WrittenClaim(
                text="Prior transformer studies suggest improved biomedical text classification.",
                claim_type="background",
                confidence=0.84,
                source_span_ids=[shared_span["span_id"]],
                is_hedged=True,
            )
        ],
        evidence_backed_sentences=["Prior transformer studies suggest improved biomedical text classification."],
        hedged_sentences=["Prior transformer studies suggest improved biomedical text classification."],
        used_source_spans=[shared_span],
    )
    sections = {
        "introduction": WrittenSection(
            section_name="introduction",
            text="Transformer-based classifiers have become a common baseline in biomedical NLP.",
            confidence=0.86,
            claims=[
                WrittenClaim(
                    text="Transformer-based classifiers have become a common baseline in biomedical NLP.",
                    claim_type="background",
                    confidence=0.86,
                    source_span_ids=[shared_span["span_id"]],
                )
            ],
            evidence_backed_sentences=["Transformer-based classifiers have become a common baseline in biomedical NLP."],
            used_source_spans=[shared_span],
        ),
        "related_work": WrittenSection(
            section_name="related_work",
            text="Several prior studies compare BERT-derived models for PubMed abstract classification.",
            confidence=0.9,
            claims=[
                WrittenClaim(
                    text="Several prior studies compare BERT-derived models for PubMed abstract classification.",
                    claim_type="prior_work",
                    confidence=0.9,
                    source_span_ids=[shared_span["span_id"]],
                )
            ],
            evidence_backed_sentences=["Several prior studies compare BERT-derived models for PubMed abstract classification."],
            used_source_spans=[shared_span],
        ),
        "methodology": WrittenSection(
            section_name="methodology",
            text="The workflow fine-tunes BioBERT on the PubMed benchmark corpus.",
            confidence=0.88,
            claims=[
                WrittenClaim(
                    text="The workflow fine-tunes BioBERT on the PubMed benchmark corpus.",
                    claim_type="methodology",
                    confidence=0.88,
                    source_span_ids=[shared_span["span_id"]],
                )
            ],
            evidence_backed_sentences=["The workflow fine-tunes BioBERT on the PubMed benchmark corpus."],
            used_source_spans=[shared_span],
        ),
        "results": WrittenSection(
            section_name="results",
            text="The proposed model outperformed the BioBERT baseline on the benchmark.",
            confidence=0.82,
            claims=[
                WrittenClaim(
                    text="The proposed model outperformed the BioBERT baseline on the benchmark.",
                    claim_type="comparison",
                    confidence=0.82,
                    source_span_ids=[shared_span["span_id"]],
                )
            ],
            evidence_backed_sentences=["The proposed model outperformed the BioBERT baseline on the benchmark."],
            used_source_spans=[shared_span],
        ),
        "discussion": WrittenSection(
            section_name="discussion",
            text="The evidence suggests that domain-specific pretraining improves biomedical relevance modelling.",
            confidence=0.71,
            claims=[
                WrittenClaim(
                    text="The evidence suggests that domain-specific pretraining improves biomedical relevance modelling.",
                    claim_type="discussion",
                    confidence=0.71,
                    source_span_ids=[shared_span["span_id"]],
                    is_inferred=True,
                    is_hedged=True,
                )
            ],
            inferred_sentences=["The evidence suggests that domain-specific pretraining improves biomedical relevance modelling."],
            hedged_sentences=["The evidence suggests that domain-specific pretraining improves biomedical relevance modelling."],
            used_source_spans=[shared_span],
        ),
        "limitations": WrittenSection(
            section_name="limitations",
            text="The evaluation remains limited to a single benchmark dataset.",
            confidence=0.55,
            claims=[],
            used_source_spans=[shared_span],
        ),
        "conclusion": WrittenSection(
            section_name="conclusion",
            text="The study supports evidence-grounded biomedical classification workflows.",
            confidence=0.76,
            claims=[
                WrittenClaim(
                    text="The study supports evidence-grounded biomedical classification workflows.",
                    claim_type="summary",
                    confidence=0.76,
                    source_span_ids=[shared_span["span_id"]],
                    is_inferred=True,
                )
            ],
            inferred_sentences=["The study supports evidence-grounded biomedical classification workflows."],
            used_source_spans=[shared_span],
        ),
    }
    return WrittenPaperDraft(
        title="Evidence-Grounded Biomedical Classification Workflow",
        abstract=abstract,
        sections=sections,
        global_confidence=0.79,
        metadata={"keywords": ["biomedical NLP", "BioBERT", "classification"]},
    )


def _build_structured_draft() -> StructuredPaperDraft:
    span = SourceSpan(
        chunk_id="chunk-001",
        start_char=0,
        end_char=120,
        quote="Transformers improved biomedical text classification.",
        relevance_score=0.91,
    )
    sections = {
        name: SectionSkeleton(
            section_name=name,
            draft=f"Draft for {name}.",
            confidence=0.8,
            key_points=[f"Point for {name}."],
            source_spans=[span],
        )
        for name in (
            "abstract",
            "introduction",
            "related_work",
            "methodology",
            "results",
            "discussion",
            "limitations",
            "conclusion",
        )
    }
    return StructuredPaperDraft(
        title_candidates=["Evidence-Grounded Biomedical Classification Workflow"],
        sections=sections,
        global_confidence=0.8,
    )


def _provider_candidate(*, provider: str, provider_id: str, title: str, doi: str | None) -> ProviderCandidate:
    return ProviderCandidate(
        candidate_id=f"{provider}:{provider_id}",
        provider=provider,
        provider_id=provider_id,
        title=title,
        authors=["A. Author", "B. Author"],
        year=2024,
        venue="Journal of Biomedical NLP",
        abstract=f"{title} studies biomedical transformer classification.",
        doi=doi,
        url=f"https://example.org/{provider_id}",
        source_query=title,
        provider_provenance=[provider],
    )


class FakeSemanticScholarClient:
    async def search_papers(self, *, query: str, limit: int):
        return [
            _provider_candidate(
                provider="semantic_scholar",
                provider_id="S2-1",
                title="BioBERT for PubMed Abstract Classification",
                doi="10.1000/semanticscholar.1",
            )
        ]

    async def fetch_papers_batch(self, *, paper_ids: list[str]):
        return {
            "S2-1": _provider_candidate(
                provider="semantic_scholar",
                provider_id="S2-1",
                title="BioBERT for PubMed Abstract Classification",
                doi="10.1000/semanticscholar.1",
            )
        }


class FakeOpenAlexClient:
    async def search_works(self, *, query: str, limit: int):
        return [
            _provider_candidate(
                provider="openalex",
                provider_id="W123",
                title="Transformer Baselines in Biomedical NLP",
                doi="10.1000/openalex.2",
            )
        ]


class FakePubMedClient:
    async def search_articles(self, *, query: str, limit: int):
        return [
            _provider_candidate(
                provider="pubmed",
                provider_id="987654",
                title="BioBERT Improves Biomedical Text Classification",
                doi="10.1000/pubmed.3",
            )
        ]


class FakeDOIClient:
    async def enrich_candidate(self, candidate: ProviderCandidate) -> ProviderCandidate:
        return candidate.model_copy(
            update={
                "doi_status": "resolved",
                "ieee_reference": f"{candidate.authors[0]}, \"{candidate.title},\" {candidate.venue}, {candidate.year}, doi: {candidate.doi}.",
            }
        )


def test_missing_written_draft_returns_structured_error():
    result = _run(run_citation_pipeline(written_draft=None, config=CitationConfig()))

    assert result.error is not None
    assert result.error.code == "missing_written_draft"
    assert result.citation_draft is None


def test_valid_flow_builds_citation_draft_with_real_shape():
    result = _run(
        run_citation_pipeline(
            written_draft=_build_written_draft(),
            structured_draft=_build_structured_draft(),
            paper_domain="biomedical NLP",
            config=CitationConfig(enable_doi_enrichment=True),
            semantic_scholar_client=FakeSemanticScholarClient(),
            openalex_client=FakeOpenAlexClient(),
            pubmed_client=FakePubMedClient(),
            doi_client=FakeDOIClient(),
        )
    )

    assert result.error is None
    assert result.citation_draft is not None
    assert result.paper_snapshot is not None
    assert result.citation_draft.bibliography
    assert result.paper_snapshot.references
    assert result.citation_draft.sections["related_work"].matches


def test_required_sections_are_present():
    result = _run(
        run_citation_pipeline(
            written_draft=_build_written_draft(),
            config=CitationConfig(),
            semantic_scholar_client=FakeSemanticScholarClient(),
            openalex_client=FakeOpenAlexClient(),
            pubmed_client=FakePubMedClient(),
            doi_client=FakeDOIClient(),
        )
    )

    assert result.citation_draft is not None
    for section_name in (
        "abstract",
        "introduction",
        "related_work",
        "methodology",
        "results",
        "discussion",
        "limitations",
        "conclusion",
    ):
        assert section_name in result.citation_draft.sections


def test_confidence_bounds_preserved_in_candidate_scores():
    result = _run(
        run_citation_pipeline(
            written_draft=_build_written_draft(),
            config=CitationConfig(),
            semantic_scholar_client=FakeSemanticScholarClient(),
            openalex_client=FakeOpenAlexClient(),
            pubmed_client=FakePubMedClient(),
            doi_client=FakeDOIClient(),
        )
    )

    assert result.citation_draft is not None
    for section in result.citation_draft.sections.values():
        for match in section.matches:
            for candidate in match.candidate_pool:
                assert candidate.scores is not None
                assert 0.0 <= candidate.scores.final_score <= 1.0


def test_deduplicated_bibliography_entries_are_generated():
    class DuplicateOpenAlex(FakeOpenAlexClient):
        async def search_works(self, *, query: str, limit: int):
            return [
                _provider_candidate(
                    provider="openalex",
                    provider_id="W123",
                    title="BioBERT for PubMed Abstract Classification",
                    doi="10.1000/semanticscholar.1",
                )
            ]

    result = _run(
        run_citation_pipeline(
            written_draft=_build_written_draft(),
            config=CitationConfig(),
            semantic_scholar_client=FakeSemanticScholarClient(),
            openalex_client=DuplicateOpenAlex(),
            pubmed_client=FakePubMedClient(),
            doi_client=FakeDOIClient(),
        )
    )

    assert result.citation_draft is not None
    dois = [entry.doi for entry in result.citation_draft.bibliography if entry.doi]
    assert len(dois) == len(set(dois))


def test_graceful_error_when_no_citations_can_be_found():
    class EmptySemanticScholar:
        async def search_papers(self, *, query: str, limit: int):
            return []

        async def fetch_papers_batch(self, *, paper_ids: list[str]):
            return {}

    class EmptyOpenAlex:
        async def search_works(self, *, query: str, limit: int):
            return []

    class EmptyPubMed:
        async def search_articles(self, *, query: str, limit: int):
            return []

    result = _run(
        run_citation_pipeline(
            written_draft=_build_written_draft(),
            config=CitationConfig(enable_doi_enrichment=False),
            semantic_scholar_client=EmptySemanticScholar(),
            openalex_client=EmptyOpenAlex(),
            pubmed_client=EmptyPubMed(),
            doi_client=FakeDOIClient(),
        )
    )

    assert result.error is not None
    assert result.error.code == "no_citations_found"


def test_compatibility_wrapper_returns_legacy_snapshot(monkeypatch: pytest.MonkeyPatch):
    pipeline_result = _run(
        run_citation_pipeline(
            written_draft=_build_written_draft(),
            config=CitationConfig(),
            semantic_scholar_client=FakeSemanticScholarClient(),
            openalex_client=FakeOpenAlexClient(),
            pubmed_client=FakePubMedClient(),
            doi_client=FakeDOIClient(),
        )
    )

    async def fake_run_citation_pipeline(**kwargs):
        return pipeline_result

    monkeypatch.setattr("agents.citation_agent.run_citation_pipeline", fake_run_citation_pipeline)

    spec = AgentSpec(
        name="citation_agent",
        role="test",
        input_schema="ResearchPaperSchema",
        output_schema="CitationAgentOutput",
        model=None,
    )
    agent = PipelineCitationAgent(mcp_server=None, spec=spec)
    snapshot = pipeline_result.paper_snapshot
    assert snapshot is not None
    payload = {
        **snapshot.model_dump(mode="python"),
        "written_draft": _build_written_draft().model_dump(mode="python"),
    }
    message = A2AMessage(
        sender="writing_agent",
        recipient="citation_agent",
        task="attach_citations",
        trace_id="trace-citation",
        payload={"paper": payload},
    )

    response_payload = _run(agent.process_task(message))
    output = CitationAgentOutput.model_validate(response_payload)
    paper_snapshot = ResearchPaperSchema.model_validate(response_payload)

    assert output.citation_draft is not None
    assert output.matched_claim_count >= 1
    assert paper_snapshot.references
