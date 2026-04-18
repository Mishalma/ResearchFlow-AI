from __future__ import annotations

import math
from dataclasses import dataclass

from core.config import Settings, get_settings
from structuring.config import StructuringConfig
from structuring.retrieval import GoogleEmbeddingProvider, MiniLMEmbeddingProvider

from citation.config import CitationConfig
from citation.schemas import CandidateScores, ClaimQuery, ProviderCandidate
from citation.utils import clamp_score, tokenize


@dataclass(frozen=True)
class RerankSummary:
    backend: str
    cross_encoder_used: bool


async def rerank_candidates(
    *,
    claim: ClaimQuery,
    candidates: list[ProviderCandidate],
    config: CitationConfig,
    settings: Settings | None = None,
    logger_=None,
) -> tuple[list[ProviderCandidate], RerankSummary]:
    if not candidates:
        return [], RerankSummary(backend="none", cross_encoder_used=False)

    lexical_scores = _compute_lexical_scores(claim=claim, candidates=candidates)
    semantic_scores, semantic_backend = await _compute_semantic_scores(
        claim=claim,
        candidates=candidates,
        settings=settings,
        logger_=logger_,
    )
    cross_encoder_scores, cross_encoder_used = await _compute_cross_encoder_scores(
        claim=claim,
        candidates=candidates,
        config=config,
        logger_=logger_,
    )

    reranked: list[ProviderCandidate] = []
    for candidate in candidates:
        lexical_score = lexical_scores.get(candidate.candidate_id, 0.0)
        semantic_score = semantic_scores.get(candidate.candidate_id, 0.0)
        cross_score = cross_encoder_scores.get(candidate.candidate_id)
        provider_score = _provider_prior(candidate.provider)
        doi_score = 1.0 if candidate.doi else 0.0
        final_score = clamp_score(
            (lexical_score * config.lexical_weight)
            + (semantic_score * config.semantic_weight)
            + ((cross_score or 0.0) * config.cross_encoder_weight)
            + (provider_score * config.provider_weight)
            + (doi_score * config.doi_weight)
        )
        reranked.append(
            candidate.model_copy(
                update={
                    "scores": CandidateScores(
                        lexical_score=lexical_score,
                        semantic_score=semantic_score,
                        cross_encoder_score=cross_score,
                        provider_score=provider_score,
                        doi_score=doi_score,
                        final_score=final_score,
                    )
                }
            )
        )

    reranked.sort(
        key=lambda item: (
            item.scores.final_score if item.scores else 0.0,
            item.citation_count or 0,
            item.year or 0,
        ),
        reverse=True,
    )
    return reranked, RerankSummary(backend=semantic_backend, cross_encoder_used=cross_encoder_used)


def _compute_lexical_scores(*, claim: ClaimQuery, candidates: list[ProviderCandidate]) -> dict[str, float]:
    claim_terms = tokenize(claim.claim_text)
    document_terms = {
        candidate.candidate_id: tokenize(f"{candidate.title} {candidate.abstract or ''}")
        for candidate in candidates
    }
    document_frequencies: dict[str, int] = {}
    for terms in document_terms.values():
        for term in set(terms):
            document_frequencies[term] = document_frequencies.get(term, 0) + 1

    raw_scores: dict[str, float] = {}
    document_count = max(len(candidates), 1)
    for candidate in candidates:
        terms = document_terms[candidate.candidate_id]
        raw_scores[candidate.candidate_id] = _bm25_like_score(
            query_terms=claim_terms,
            document_terms=terms,
            document_frequencies=document_frequencies,
            document_count=document_count,
        )
    return _normalize_score_map(raw_scores)


async def _compute_semantic_scores(
    *,
    claim: ClaimQuery,
    candidates: list[ProviderCandidate],
    settings: Settings | None,
    logger_,
) -> tuple[dict[str, float], str]:
    resolved_settings = settings or get_settings()
    structuring_config = StructuringConfig.from_settings(resolved_settings)
    texts = [claim.claim_text, *[f"{candidate.title}. {candidate.abstract or ''}" for candidate in candidates]]
    providers = [
        ("google", GoogleEmbeddingProvider(resolved_settings, structuring_config)),
        ("all-minilm-l6-v2", MiniLMEmbeddingProvider(structuring_config)),
    ]
    for backend_name, provider in providers:
        try:
            vectors = await _embed_with_provider(provider, texts)
            if len(vectors) != len(texts):
                raise ValueError("embedding backend returned mismatched vector count")
            query_vector = vectors[0]
            raw_scores = {
                candidate.candidate_id: _cosine_similarity(query_vector, vectors[index + 1])
                for index, candidate in enumerate(candidates)
            }
            return _normalize_score_map(raw_scores), backend_name
        except Exception as exc:  # pragma: no cover - backend/environment dependent
            if logger_ is not None:
                logger_.warning("Citation semantic reranking backend %s unavailable: %s", backend_name, exc)
    return {candidate.candidate_id: 0.0 for candidate in candidates}, "lexical"


async def _compute_cross_encoder_scores(
    *,
    claim: ClaimQuery,
    candidates: list[ProviderCandidate],
    config: CitationConfig,
    logger_,
) -> tuple[dict[str, float], bool]:
    if not config.enable_cross_encoder:
        return {}, False
    try:
        from sentence_transformers import CrossEncoder
    except Exception as exc:  # pragma: no cover - optional dependency
        if logger_ is not None:
            logger_.warning("Citation cross-encoder is unavailable: %s", exc)
        return {}, False

    model = CrossEncoder(config.cross_encoder_model)
    pairs = [(claim.claim_text, f"{candidate.title}. {candidate.abstract or ''}") for candidate in candidates]
    try:
        raw_scores = model.predict(pairs)
    except Exception as exc:  # pragma: no cover - model/runtime dependent
        if logger_ is not None:
            logger_.warning("Citation cross-encoder prediction failed: %s", exc)
        return {}, False

    scored = {
        candidate.candidate_id: float(raw_scores[index])
        for index, candidate in enumerate(candidates)
    }
    return _normalize_score_map(scored), True


async def _embed_with_provider(provider, texts: list[str]) -> list[list[float]]:
    import asyncio

    return await asyncio.to_thread(provider.embed_texts, texts)


def _provider_prior(provider_name: str) -> float:
    priors = {
        "semantic_scholar": 0.9,
        "openalex": 0.8,
        "pubmed": 0.95,
    }
    return priors.get(provider_name, 0.6)


def _bm25_like_score(
    *,
    query_terms: list[str],
    document_terms: list[str],
    document_frequencies: dict[str, int],
    document_count: int,
) -> float:
    if not query_terms or not document_terms:
        return 0.0
    term_counts: dict[str, int] = {}
    for term in document_terms:
        term_counts[term] = term_counts.get(term, 0) + 1

    k1 = 1.2
    b = 0.75
    avg_len = max(len(document_terms), 1)
    score = 0.0
    for term in query_terms:
        tf = term_counts.get(term, 0)
        if tf <= 0:
            continue
        df = document_frequencies.get(term, 0)
        idf = math.log(((document_count - df + 0.5) / (df + 0.5)) + 1.0)
        denominator = tf + k1 * (1 - b + (b * len(document_terms) / avg_len))
        score += idf * ((tf * (k1 + 1)) / max(denominator, 1e-6))
    score += _token_overlap(query_terms, document_terms)
    return score


def _token_overlap(query_terms: list[str], document_terms: list[str]) -> float:
    query_set = set(query_terms)
    document_set = set(document_terms)
    if not query_set or not document_set:
        return 0.0
    return len(query_set & document_set) / len(query_set | document_set)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if math.isclose(left_norm, 0.0) or math.isclose(right_norm, 0.0):
        return 0.0
    return max(0.0, numerator / (left_norm * right_norm))


def _normalize_score_map(raw_scores: dict[str, float]) -> dict[str, float]:
    if not raw_scores:
        return {}
    maximum = max(raw_scores.values())
    minimum = min(raw_scores.values())
    if math.isclose(maximum, minimum):
        return {key: (1.0 if maximum > 0 else 0.0) for key in raw_scores}
    return {
        key: clamp_score((value - minimum) / (maximum - minimum))
        for key, value in raw_scores.items()
    }
