from __future__ import annotations

import asyncio
import logging

from citation.bibliography import build_bibliography
from citation.claim_extractor import extract_claim_queries
from citation.config import CitationConfig
from citation.doi import DOIClient
from citation.provider_clients import OpenAlexClient, PubMedClient, SemanticScholarClient
from citation.query_builder import enrich_claim_query
from citation.reranker import rerank_candidates
from citation.schemas import CitationDraft, ClaimQuery, MatchedCitation, ProviderCandidate, SectionCitationResult
from citation.utils import build_provider_summary, candidate_dedupe_key, merge_dicts
from core.config import Settings
from structuring.schemas import StructuredPaperDraft
from writing.schemas import WrittenPaperDraft

logger = logging.getLogger("papereasy.backend.citation.retrieval")


async def build_citation_draft(
    *,
    written_draft: WrittenPaperDraft,
    structured_draft: StructuredPaperDraft | None,
    config: CitationConfig,
    settings: Settings,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    trace_id: str,
    semantic_scholar_client: SemanticScholarClient | None = None,
    openalex_client: OpenAlexClient | None = None,
    pubmed_client: PubMedClient | None = None,
    doi_client: DOIClient | None = None,
    logger_: logging.Logger | None = None,
) -> CitationDraft:
    active_logger = logger_ or logger
    semantic_client = semantic_scholar_client or SemanticScholarClient(config)
    openalex = openalex_client or OpenAlexClient(config)
    pubmed = pubmed_client or PubMedClient(config)
    doi_resolver = doi_client or (DOIClient(config) if config.enable_doi_enrichment else None)

    extracted_claims = extract_claim_queries(
        written_draft=written_draft,
        structured_draft=structured_draft,
        paper_topic=paper_topic,
        paper_domain=paper_domain,
        logger_=active_logger,
    )
    query_plan = {
        section_name: [
            enrich_claim_query(
                claim=claim,
                paper_topic=paper_topic,
                paper_domain=paper_domain,
                max_queries=config.max_queries_per_claim,
            )
            for claim in claims
        ]
        for section_name, claims in extracted_claims.items()
    }

    semaphore = asyncio.Semaphore(config.max_parallel_claims)
    tasks = [
        _match_claim(
            claim=claim,
            config=config,
            settings=settings,
            semaphore=semaphore,
            semantic_scholar_client=semantic_client,
            openalex_client=openalex,
            pubmed_client=pubmed,
            logger_=active_logger,
        )
        for claims in query_plan.values()
        for claim in claims
    ]
    matched_results = await asyncio.gather(*tasks) if tasks else []

    all_matches = list(matched_results)
    bibliography, updated_matches = await build_bibliography(
        matches=all_matches,
        doi_client=doi_resolver,
        max_entries=config.max_bibliography_entries,
        logger_=active_logger,
    )
    updated_lookup = {match.claim_id: match for match in updated_matches}

    section_results: dict[str, SectionCitationResult] = {}
    provider_usage: list[str] = []
    for section_name, claims in query_plan.items():
        matches = [updated_lookup[claim.claim_id] for claim in claims if claim.claim_id in updated_lookup]
        providers = [
            provider
            for match in matches
            for candidate in match.selected_candidates
            for provider in candidate.provider_provenance
        ]
        provider_usage.extend(providers)
        section_results[section_name] = SectionCitationResult(
            section_name=section_name,
            claims=claims,
            matches=matches,
            provider_summary=build_provider_summary(providers),
        )

    return CitationDraft(
        title=written_draft.title,
        sections=section_results,
        bibliography=bibliography,
        provider_summary=build_provider_summary(provider_usage),
        metadata={
            "trace_id": trace_id,
            "query_counts": {section_name: len(claims) for section_name, claims in query_plan.items()},
        },
    )


async def _match_claim(
    *,
    claim: ClaimQuery,
    config: CitationConfig,
    settings: Settings,
    semaphore: asyncio.Semaphore,
    semantic_scholar_client: SemanticScholarClient,
    openalex_client: OpenAlexClient,
    pubmed_client: PubMedClient,
    logger_: logging.Logger,
) -> MatchedCitation:
    async with semaphore:
        raw_candidates = await _retrieve_candidates_for_claim(
            claim=claim,
            config=config,
            semantic_scholar_client=semantic_scholar_client,
            openalex_client=openalex_client,
            pubmed_client=pubmed_client,
            logger_=logger_,
        )
        deduped_candidates = _deduplicate_candidates(raw_candidates)
        reranked_candidates, rerank_summary = await rerank_candidates(
            claim=claim,
            candidates=deduped_candidates[: config.top_candidates_for_rerank],
            config=config,
            settings=settings,
            logger_=logger_,
        )
        selected_candidates = _select_candidates(
            claim=claim,
            candidates=reranked_candidates,
            max_selected=config.max_selected_citations_per_claim,
        )
        notes = [f"Semantic reranking backend: {rerank_summary.backend}"]
        if rerank_summary.cross_encoder_used:
            notes.append("Cross-encoder reranking applied.")
        if not selected_candidates:
            notes.append("No candidate passed the final selection threshold.")
        return MatchedCitation(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            selected_candidates=selected_candidates,
            candidate_pool=reranked_candidates[: config.top_candidates_for_rerank],
            status="matched" if selected_candidates else "unmatched",
            notes=notes,
        )


async def _retrieve_candidates_for_claim(
    *,
    claim: ClaimQuery,
    config: CitationConfig,
    semantic_scholar_client: SemanticScholarClient,
    openalex_client: OpenAlexClient,
    pubmed_client: PubMedClient,
    logger_: logging.Logger,
) -> list[ProviderCandidate]:
    tasks = []
    for provider_name in claim.provider_route:
        for query in claim.search_queries:
            if provider_name == "semantic_scholar":
                tasks.append(semantic_scholar_client.search_papers(query=query, limit=config.max_results_per_provider))
            elif provider_name == "openalex":
                tasks.append(openalex_client.search_works(query=query, limit=config.max_results_per_provider))
            elif provider_name == "pubmed":
                tasks.append(pubmed_client.search_articles(query=query, limit=min(config.max_results_per_provider, 6)))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    flattened: list[ProviderCandidate] = []
    semantic_ids: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            logger_.warning("Citation provider request failed for claim %s: %s", claim.claim_id, result)
            continue
        flattened.extend(result)
        semantic_ids.extend(
            candidate.provider_id
            for candidate in result
            if candidate.provider == "semantic_scholar" and (not candidate.abstract or not candidate.doi)
        )

    if semantic_ids:
        try:
            enriched = await semantic_scholar_client.fetch_papers_batch(paper_ids=list(dict.fromkeys(semantic_ids)))
            flattened = [
                _merge_candidates(candidate, enriched.get(candidate.provider_id))
                if candidate.provider == "semantic_scholar"
                else candidate
                for candidate in flattened
            ]
        except Exception as exc:  # pragma: no cover - network dependent
            logger_.warning("Semantic Scholar batch enrichment failed for claim %s: %s", claim.claim_id, exc)
    return flattened


def _deduplicate_candidates(candidates: list[ProviderCandidate]) -> list[ProviderCandidate]:
    deduped: dict[str, ProviderCandidate] = {}
    for candidate in candidates:
        key = candidate_dedupe_key(title=candidate.title, doi=candidate.doi, year=candidate.year)
        if key not in deduped:
            deduped[key] = candidate
            continue
        existing = deduped[key]
        deduped[key] = existing.model_copy(
            update={
                "authors": existing.authors or candidate.authors,
                "year": existing.year or candidate.year,
                "venue": existing.venue or candidate.venue,
                "abstract": existing.abstract or candidate.abstract,
                "doi": existing.doi or candidate.doi,
                "url": existing.url or candidate.url,
                "citation_count": max(existing.citation_count or 0, candidate.citation_count or 0) or None,
                "external_ids": merge_dicts(existing.external_ids, candidate.external_ids),
                "provider_provenance": list(dict.fromkeys([*existing.provider_provenance, *candidate.provider_provenance, candidate.provider])),
                "metadata": merge_dicts(existing.metadata, candidate.metadata),
            }
        )
    return list(deduped.values())


def _select_candidates(
    *,
    claim: ClaimQuery,
    candidates: list[ProviderCandidate],
    max_selected: int,
) -> list[ProviderCandidate]:
    if not candidates:
        return []
    threshold = 0.46 if claim.claim_type in {"prior_work_claim", "comparative_state_of_the_art_claim"} else 0.42
    selected: list[ProviderCandidate] = []
    for candidate in candidates:
        final_score = candidate.scores.final_score if candidate.scores is not None else 0.0
        if final_score < threshold and selected:
            continue
        if final_score < 0.38 and not selected:
            continue
        selected.append(candidate)
        if len(selected) >= max_selected:
            break
    return selected


def _merge_candidates(left: ProviderCandidate, right: ProviderCandidate | None) -> ProviderCandidate:
    if right is None:
        return left
    return left.model_copy(
        update={
            "authors": left.authors or right.authors,
            "year": left.year or right.year,
            "venue": left.venue or right.venue,
            "abstract": left.abstract or right.abstract,
            "doi": left.doi or right.doi,
            "url": left.url or right.url,
            "citation_count": max(left.citation_count or 0, right.citation_count or 0) or None,
            "external_ids": merge_dicts(left.external_ids, right.external_ids),
            "provider_provenance": list(dict.fromkeys([*left.provider_provenance, *right.provider_provenance])),
            "metadata": merge_dicts(left.metadata, right.metadata),
        }
    )
