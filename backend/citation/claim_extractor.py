from __future__ import annotations

import logging

from structuring.schemas import StructuredPaperDraft
from writing.schemas import WrittenClaim, WrittenPaperDraft, WrittenSection

from citation.schemas import ClaimQuery
from citation.utils import (
    claim_requires_citation,
    detect_claim_type,
    provider_route_for_claim,
    truncate_query,
)

logger = logging.getLogger("papereasy.backend.citation.claim_extractor")


def extract_claim_queries(
    *,
    written_draft: WrittenPaperDraft,
    structured_draft: StructuredPaperDraft | None = None,
    paper_topic: str | None = None,
    paper_domain: str | None = None,
    max_claims_per_section: int | None = None,
    logger_: logging.Logger | None = None,
) -> dict[str, list[ClaimQuery]]:
    active_logger = logger_ or logger
    extracted: dict[str, list[ClaimQuery]] = {}
    structured_lookup = _build_structured_span_lookup(structured_draft)

    ordered_sections: list[tuple[str, WrittenSection]] = [("abstract", written_draft.abstract)]
    ordered_sections.extend((name, section) for name, section in written_draft.sections.items())

    for section_name, section in ordered_sections:
        claim_queries: list[ClaimQuery] = []
        used_spans = list(section.used_source_spans)
        claim_source = list(section.claims) or _claims_from_sentences(section)

        for index, claim in enumerate(claim_source, start=1):
            claim_type = detect_claim_type(section_name, claim.text)
            if not claim_requires_citation(section_name, claim.text, claim_type):
                continue

            source_span_ids = list(claim.source_span_ids)
            section_spans = _resolve_source_spans(
                source_span_ids=source_span_ids,
                used_source_spans=used_spans,
                structured_lookup=structured_lookup,
            )
            claim_queries.append(
                ClaimQuery(
                    claim_id=f"{section_name}-claim-{index:03d}",
                    section_name=section_name,
                    claim_text=claim.text,
                    claim_type=claim_type,
                    confidence=claim.confidence,
                    evidence_class=_resolve_evidence_class(claim, section),
                    source_span_ids=source_span_ids,
                    source_spans=section_spans,
                    search_queries=[truncate_query(claim.text)],
                    provider_route=provider_route_for_claim(claim_type, claim.text, paper_domain),
                    requires_external_citation=True,
                    notes=_build_claim_notes(claim, paper_topic, paper_domain),
                )
            )

        if max_claims_per_section is not None and len(claim_queries) > max_claims_per_section:
            claim_queries = _prioritize_claims(claim_queries, limit=max_claims_per_section)
            claim_queries = [
                claim.model_copy(update={"claim_id": f"{section_name}-claim-{index:03d}"})
                for index, claim in enumerate(claim_queries, start=1)
            ]

        extracted[section_name] = claim_queries
        active_logger.info(
            "Citation claim extraction for section %s produced %s citation-needed claims.",
            section_name,
            len(claim_queries),
        )

    return extracted


def _claims_from_sentences(section: WrittenSection) -> list[WrittenClaim]:
    claim_texts = list(section.evidence_backed_sentences) + list(section.inferred_sentences)
    if not claim_texts:
        text = section.text.strip()
        if text:
            claim_texts = [segment.strip() for segment in text.split(". ") if segment.strip()]
    claims: list[WrittenClaim] = []
    for sentence in claim_texts:
        claims.append(
            WrittenClaim(
                text=sentence.strip().rstrip(".") + ".",
                claim_type="context",
                confidence=section.confidence,
                source_span_ids=[span.get("span_id", "") for span in section.used_source_spans if span.get("span_id")],
                is_inferred=sentence in section.inferred_sentences,
                is_hedged=sentence in section.hedged_sentences,
            )
        )
    return claims


def _resolve_evidence_class(claim: WrittenClaim, section: WrittenSection) -> str:
    if claim.text in section.evidence_backed_sentences:
        return "evidence_backed"
    if claim.text in section.inferred_sentences or claim.is_inferred:
        return "inferred"
    if claim.text in section.hedged_sentences or claim.is_hedged:
        return "hedged"
    return "context"


def _build_claim_notes(claim: WrittenClaim, paper_topic: str | None, paper_domain: str | None) -> list[str]:
    notes: list[str] = []
    if claim.is_inferred:
        notes.append("Claim contains inferred synthesis and should prefer cautious matching.")
    if claim.is_hedged:
        notes.append("Claim is already hedged and supporting citations should not intensify certainty.")
    if paper_topic:
        notes.append(f"Paper topic context: {paper_topic.strip()}")
    if paper_domain:
        notes.append(f"Paper domain context: {paper_domain.strip()}")
    return notes


def _resolve_source_spans(
    *,
    source_span_ids: list[str],
    used_source_spans: list[dict],
    structured_lookup: dict[str, dict],
) -> list[dict]:
    if not source_span_ids:
        return list(used_source_spans)

    resolved: list[dict] = []
    seen: set[str] = set()
    for span_id in source_span_ids:
        if span_id in seen:
            continue
        seen.add(span_id)
        for span in used_source_spans:
            if span.get("span_id") == span_id:
                resolved.append(dict(span))
                break
        else:
            if span_id in structured_lookup:
                resolved.append(dict(structured_lookup[span_id]))
    return resolved


def _build_structured_span_lookup(structured_draft: StructuredPaperDraft | None) -> dict[str, dict]:
    if structured_draft is None:
        return {}
    lookup: dict[str, dict] = {}
    for section in structured_draft.sections.values():
        for span in section.source_spans:
            span_id = f"{span.chunk_id}:{span.start_char}:{span.end_char}"
            lookup[span_id] = {
                "span_id": span_id,
                "chunk_id": span.chunk_id,
                "start_char": span.start_char,
                "end_char": span.end_char,
                "quote": span.quote,
                "relevance_score": span.relevance_score,
            }
    return lookup


def _prioritize_claims(claims: list[ClaimQuery], *, limit: int) -> list[ClaimQuery]:
    prioritized = sorted(
        claims,
        key=lambda claim: (
            _claim_priority(claim),
            len(claim.source_spans),
            len(claim.claim_text),
        ),
        reverse=True,
    )
    return prioritized[:limit]


def _claim_priority(claim: ClaimQuery) -> float:
    priority = float(claim.confidence)
    if claim.evidence_class == "evidence_backed":
        priority += 0.3
    elif claim.evidence_class == "inferred":
        priority -= 0.12
    elif claim.evidence_class == "hedged":
        priority -= 0.08

    if claim.claim_type in {
        "prior_work_claim",
        "comparative_state_of_the_art_claim",
        "methodology_provenance_claim",
        "dataset_tool_claim",
        "domain_fact_claim",
    }:
        priority += 0.12
    return priority
