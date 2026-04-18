from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Protocol

from core.config import Settings, get_settings
from structuring.config import StructuringConfig
from structuring.schemas import TextChunk

logger = logging.getLogger("papereasy.backend.structuring.retrieval")

SECTION_INTENT_QUERIES: dict[str, str] = {
    "title": "paper title research topic contribution system study",
    "abstract": "abstract summary objective contribution findings overview",
    "introduction": "introduction problem motivation objective context challenge contribution",
    "related_work": "related work literature review prior research existing approaches baseline comparison",
    "methodology": "methods procedure system implementation experimental setup algorithm pipeline dataset",
    "results": "results findings metrics evaluation performance accuracy comparison benchmark",
    "discussion": "discussion interpretation implications analysis tradeoffs significance lessons learned",
    "limitations": "limitations constraints threats to validity failure cases assumptions risks future improvements",
    "conclusion": "conclusion summary takeaway final remarks future work contributions",
}

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "with",
}


@dataclass(frozen=True)
class RankedChunk:
    chunk: TextChunk
    relevance_score: float


@dataclass(frozen=True)
class SectionRetrievalResult:
    section_name: str
    query: str
    backend: str
    candidates: list[RankedChunk]


class EmbeddingProvider(Protocol):
    backend_name: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class GoogleEmbeddingProvider:
    backend_name = "google"

    def __init__(
        self,
        settings: Settings | None = None,
        config: StructuringConfig | None = None,
    ):
        self.settings = settings or get_settings()
        self.config = config or StructuringConfig.from_settings(self.settings)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        from google import genai
        from google.genai import types

        credentials = _build_google_credentials(self.settings)
        client = genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
            credentials=credentials,
            http_options=types.HttpOptions(api_version="v1"),
        )
        try:
            response = client.models.embed_content(
                model=self.config.google_embedding_model,
                contents=texts,
            )
            return [embedding.values for embedding in response.embeddings or []]
        finally:
            client.close()


class MiniLMEmbeddingProvider:
    backend_name = "all-minilm-l6-v2"
    _model = None

    def __init__(self, config: StructuringConfig | None = None):
        self.config = config or StructuringConfig()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from sentence_transformers import SentenceTransformer

        if MiniLMEmbeddingProvider._model is None:
            MiniLMEmbeddingProvider._model = SentenceTransformer(
                self.config.local_embedding_model,
                local_files_only=True,
            )
        matrix = MiniLMEmbeddingProvider._model.encode(texts, normalize_embeddings=False)
        return [list(vector) for vector in matrix]


def retrieve_section_candidates(
    *,
    chunks: list[TextChunk],
    config: StructuringConfig,
    settings: Settings | None = None,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    logger_: logging.Logger | None = None,
) -> tuple[dict[str, SectionRetrievalResult], str]:
    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    queries = _build_section_queries(paper_topic=paper_topic, paper_domain=paper_domain)

    providers: list[EmbeddingProvider] = []
    if embedding_provider is not None:
        providers.append(embedding_provider)
    else:
        providers.extend(
            [
                GoogleEmbeddingProvider(resolved_settings, config),
                MiniLMEmbeddingProvider(config),
            ]
        )

    if chunks:
        for provider in providers:
            try:
                results = _retrieve_with_embeddings(
                    chunks=chunks,
                    queries=queries,
                    provider=provider,
                    config=config,
                )
                active_logger.info("Structuring retrieval used %s embeddings.", provider.backend_name)
                return results, provider.backend_name
            except Exception as exc:  # pragma: no cover - backend/environment dependent
                active_logger.warning(
                    "Structuring retrieval backend %s unavailable: %s",
                    provider.backend_name,
                    exc,
                )

    lexical_results = _retrieve_lexically(chunks=chunks, queries=queries, config=config)
    active_logger.info("Structuring retrieval fell back to lexical scoring.")
    return lexical_results, "lexical"


def _retrieve_with_embeddings(
    *,
    chunks: list[TextChunk],
    queries: dict[str, str],
    provider: EmbeddingProvider,
    config: StructuringConfig,
) -> dict[str, SectionRetrievalResult]:
    query_names = list(queries.keys())
    query_embeddings = provider.embed_texts([queries[name] for name in query_names])
    chunk_embeddings = provider.embed_texts([chunk.text for chunk in chunks])
    if len(query_embeddings) != len(query_names) or len(chunk_embeddings) != len(chunks):
        raise ValueError("embedding provider returned mismatched vector counts")

    results: dict[str, SectionRetrievalResult] = {}
    for section_name, query_vector in zip(query_names, query_embeddings, strict=True):
        raw_scores = [
            _cosine_similarity(query_vector, chunk_vector)
            for chunk_vector in chunk_embeddings
        ]
        normalized_scores = _normalize_scores(raw_scores)
        ranked = [
            RankedChunk(chunk=chunk, relevance_score=score)
            for chunk, score in zip(chunks, normalized_scores, strict=True)
            if score > 0
        ]
        ranked.sort(key=lambda item: item.relevance_score, reverse=True)
        results[section_name] = SectionRetrievalResult(
            section_name=section_name,
            query=queries[section_name],
            backend=provider.backend_name,
            candidates=ranked[: config.top_k_per_section],
        )
    return results


def _retrieve_lexically(
    *,
    chunks: list[TextChunk],
    queries: dict[str, str],
    config: StructuringConfig,
) -> dict[str, SectionRetrievalResult]:
    chunk_terms = [_tokenize(chunk.text) for chunk in chunks]
    document_frequencies: dict[str, int] = {}
    for terms in chunk_terms:
        for term in set(terms):
            document_frequencies[term] = document_frequencies.get(term, 0) + 1

    results: dict[str, SectionRetrievalResult] = {}
    for section_name, query in queries.items():
        query_terms = _tokenize(query)
        raw_scores = [
            _lexical_score(
                query_terms=query_terms,
                chunk_terms=terms,
                document_frequencies=document_frequencies,
                document_count=max(len(chunks), 1),
            )
            for terms in chunk_terms
        ]
        normalized_scores = _normalize_scores(raw_scores)
        ranked = [
            RankedChunk(chunk=chunk, relevance_score=score)
            for chunk, score in zip(chunks, normalized_scores, strict=True)
            if score >= config.lexical_min_score
        ]
        ranked.sort(key=lambda item: item.relevance_score, reverse=True)
        results[section_name] = SectionRetrievalResult(
            section_name=section_name,
            query=query,
            backend="lexical",
            candidates=ranked[: config.lexical_candidate_pool],
        )
    return results


def _build_section_queries(
    *,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
) -> dict[str, str]:
    suffix_parts = [value.strip() for value in (paper_topic, paper_domain) if value and value.strip()]
    suffix = f" {' '.join(suffix_parts)}" if suffix_parts else ""
    return {
        section_name: f"{query}{suffix}".strip()
        for section_name, query in SECTION_INTENT_QUERIES.items()
    }


def _build_google_credentials(settings: Settings):
    raw_adc_path = settings.vertex_service_account_file
    if raw_adc_path is None:
        env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        raw_adc_path = env_path or None
    if raw_adc_path is None:
        return None

    from google.oauth2 import service_account

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    return service_account.Credentials.from_service_account_file(
        str(raw_adc_path),
        scopes=scopes,
    )


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def _lexical_score(
    *,
    query_terms: list[str],
    chunk_terms: list[str],
    document_frequencies: dict[str, int],
    document_count: int,
) -> float:
    if not query_terms or not chunk_terms:
        return 0.0

    term_counts: dict[str, int] = {}
    for term in chunk_terms:
        term_counts[term] = term_counts.get(term, 0) + 1

    score = 0.0
    denominator = len(chunk_terms) + 1.2
    for term in query_terms:
        tf = term_counts.get(term, 0)
        if tf <= 0:
            continue
        df = document_frequencies.get(term, 0)
        idf = math.log((1 + document_count) / (1 + df)) + 1.0
        score += (tf / denominator) * idf

    overlap = len(set(query_terms) & set(chunk_terms))
    score += overlap / max(len(set(query_terms)), 1)
    return score


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    max_score = max(scores)
    min_score = min(scores)
    if math.isclose(max_score, min_score):
        return [1.0 if max_score > 0 else 0.0 for _ in scores]
    return [(score - min_score) / (max_score - min_score) for score in scores]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if math.isclose(left_norm, 0.0) or math.isclose(right_norm, 0.0):
        return 0.0
    return max(0.0, numerator / (left_norm * right_norm))
