from __future__ import annotations

from citation.schemas import ClaimQuery
from citation.utils import tokenize, truncate_query


def enrich_claim_query(
    *,
    claim: ClaimQuery,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    max_queries: int = 3,
) -> ClaimQuery:
    queries = build_search_queries(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        section_name=claim.section_name,
        paper_topic=paper_topic,
        paper_domain=paper_domain,
        max_queries=max_queries,
    )
    return claim.model_copy(update={"search_queries": queries})


def build_search_queries(
    *,
    claim_text: str,
    claim_type: str,
    section_name: str,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    max_queries: int = 3,
) -> list[str]:
    base_query = truncate_query(claim_text, max_tokens=18)
    topic_query = truncate_query(f"{claim_text} {paper_topic or ''} {paper_domain or ''}", max_tokens=18)
    keyword_tail = []
    if claim_type == "prior_work_claim":
        keyword_tail = ["prior work", "survey", "baseline"]
    elif claim_type == "comparative_state_of_the_art_claim":
        keyword_tail = ["benchmark", "comparison", "state of the art"]
    elif claim_type == "methodology_provenance_claim":
        keyword_tail = ["method", "dataset", "implementation"]
    elif claim_type == "dataset_tool_claim":
        keyword_tail = ["dataset", "tool", "benchmark"]
    elif claim_type == "biomedical_mechanistic_claim":
        keyword_tail = ["clinical", "study", "pubmed"]
    elif section_name in {"introduction", "discussion", "conclusion"}:
        keyword_tail = ["study", "analysis"]

    keyword_query = truncate_query(" ".join([claim_text, *keyword_tail]), max_tokens=18)

    candidates = [base_query, topic_query, keyword_query]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = " ".join(candidate.split()).strip()
        if not cleaned:
            continue
        signature = " ".join(tokenize(cleaned))
        if not signature or signature in seen:
            continue
        seen.add(signature)
        deduplicated.append(cleaned)
        if len(deduplicated) >= max_queries:
            break
    return deduplicated or [truncate_query(claim_text, max_tokens=12)]
