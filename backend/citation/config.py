from __future__ import annotations

import os
from dataclasses import dataclass

from core.config import Settings, get_settings


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CitationConfig:
    semantic_scholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    openalex_base_url: str = "https://api.openalex.org"
    ncbi_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    doi_base_url: str = "https://doi.org"
    crossref_base_url: str = "https://api.crossref.org"
    semantic_scholar_api_key: str | None = None
    openalex_api_key: str | None = None
    ncbi_api_key: str | None = None
    ncbi_tool: str = "papereasy-citation-agent"
    ncbi_email: str | None = None
    openalex_mailto: str | None = None
    crossref_mailto: str | None = None
    http_timeout_seconds: int = 15
    max_results_per_provider: int = 8
    max_queries_per_claim: int = 2
    max_claims_per_section: int = 3
    max_parallel_claims: int = 6
    max_parallel_requests_per_claim: int = 4
    max_selected_citations_per_claim: int = 2
    max_bibliography_entries: int = 12
    top_candidates_for_rerank: int = 10
    lexical_weight: float = 0.35
    semantic_weight: float = 0.35
    cross_encoder_weight: float = 0.2
    provider_weight: float = 0.05
    doi_weight: float = 0.05
    semantic_embedding_model: str = "text-embedding-005"
    local_embedding_model: str = "all-MiniLM-L6-v2"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    enable_cross_encoder: bool = False
    enable_doi_enrichment: bool = True
    enable_crossref_enrichment: bool = True
    debug_logging: bool = False

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "CitationConfig":
        resolved_settings = settings or get_settings()
        citation_limit = max(1, resolved_settings.citation_result_limit)
        return cls(
            semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip() or None,
            openalex_api_key=os.getenv("OPENALEX_API_KEY", "").strip() or None,
            ncbi_api_key=os.getenv("NCBI_API_KEY", "").strip() or None,
            ncbi_tool=os.getenv("NCBI_TOOL", "papereasy-citation-agent").strip() or "papereasy-citation-agent",
            ncbi_email=os.getenv("NCBI_EMAIL", "").strip() or None,
            openalex_mailto=os.getenv("OPENALEX_MAILTO", "").strip() or os.getenv("NCBI_EMAIL", "").strip() or None,
            crossref_mailto=os.getenv("CROSSREF_MAILTO", "").strip() or os.getenv("NCBI_EMAIL", "").strip() or None,
            http_timeout_seconds=max(5, int(os.getenv("CITATION_HTTP_TIMEOUT_SECONDS", "15"))),
            max_results_per_provider=max(3, int(os.getenv("CITATION_PROVIDER_RESULT_LIMIT", str(max(6, citation_limit * 2))))),
            max_queries_per_claim=max(1, int(os.getenv("CITATION_MAX_QUERIES_PER_CLAIM", "2"))),
            max_claims_per_section=max(1, int(os.getenv("CITATION_MAX_CLAIMS_PER_SECTION", "3"))),
            max_parallel_claims=max(1, int(os.getenv("CITATION_MAX_PARALLEL_CLAIMS", "6"))),
            max_parallel_requests_per_claim=max(1, int(os.getenv("CITATION_MAX_PARALLEL_REQUESTS_PER_CLAIM", "4"))),
            max_selected_citations_per_claim=max(1, min(3, int(os.getenv("CITATION_MAX_SELECTED_PER_CLAIM", str(min(2, citation_limit)))))),
            max_bibliography_entries=max(4, int(os.getenv("CITATION_MAX_BIBLIOGRAPHY_ENTRIES", str(max(8, citation_limit * 3))))),
            top_candidates_for_rerank=max(3, int(os.getenv("CITATION_TOP_CANDIDATES_FOR_RERANK", "10"))),
            enable_cross_encoder=_get_bool("CITATION_ENABLE_CROSS_ENCODER", False),
            enable_doi_enrichment=_get_bool("CITATION_ENABLE_DOI_ENRICHMENT", True),
            enable_crossref_enrichment=_get_bool("CITATION_ENABLE_CROSSREF_ENRICHMENT", True),
            debug_logging=_get_bool("CITATION_DEBUG_LOGGING", resolved_settings.debug),
        )
