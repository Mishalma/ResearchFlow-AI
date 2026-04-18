from __future__ import annotations

import logging
from collections import OrderedDict

from citation.doi import DOIClient
from citation.schemas import BibliographyEntry, MatchedCitation, ProviderCandidate
from citation.utils import candidate_dedupe_key, normalize_doi, normalize_whitespace

logger = logging.getLogger("papereasy.backend.citation.bibliography")


async def build_bibliography(
    *,
    matches: list[MatchedCitation],
    doi_client: DOIClient | None,
    max_entries: int,
    logger_: logging.Logger | None = None,
) -> tuple[list[BibliographyEntry], list[MatchedCitation]]:
    active_logger = logger_ or logger
    bibliography_map: "OrderedDict[str, BibliographyEntry]" = OrderedDict()
    updated_matches: list[MatchedCitation] = []

    for match in matches:
        entry_ids: list[str] = []
        updated_candidates: list[ProviderCandidate] = []
        for candidate in match.selected_candidates:
            enriched = candidate
            if doi_client is not None and candidate.doi:
                try:
                    enriched = await doi_client.enrich_candidate(candidate)
                except Exception as exc:  # pragma: no cover - network dependent
                    active_logger.warning("DOI enrichment failed for %s: %s", candidate.doi, exc)
            key = candidate_dedupe_key(title=enriched.title, doi=enriched.doi, year=enriched.year)
            if key not in bibliography_map and len(bibliography_map) < max_entries:
                bibliography_map[key] = BibliographyEntry(
                    entry_id=f"ref-{len(bibliography_map) + 1:03d}",
                    citation_number=len(bibliography_map) + 1,
                    title=enriched.title,
                    ieee_reference=_format_ieee_reference(enriched),
                    doi=normalize_doi(enriched.doi),
                    providers=list(enriched.provider_provenance),
                    authors=list(enriched.authors),
                    year=enriched.year,
                    venue=enriched.venue,
                    url=enriched.url,
                )
            entry = bibliography_map.get(key)
            if entry is not None:
                entry_ids.append(entry.entry_id)
            updated_candidates.append(enriched)
        updated_matches.append(
            match.model_copy(
                update={
                    "selected_candidates": updated_candidates,
                    "bibliography_entry_ids": entry_ids,
                }
            )
        )
    return list(bibliography_map.values()), updated_matches


def _format_ieee_reference(candidate: ProviderCandidate) -> str:
    if candidate.ieee_reference:
        return candidate.ieee_reference
    authors = _format_authors(candidate.authors)
    title = f"\"{normalize_whitespace(candidate.title)}\""
    venue = normalize_whitespace(candidate.venue or "")
    year = str(candidate.year) if candidate.year else "n.d."
    parts = [part for part in [authors, title, venue, year] if part]
    reference = ", ".join(parts)
    if candidate.doi:
        reference = f"{reference}, doi: {candidate.doi}"
    if candidate.url and not candidate.doi:
        reference = f"{reference}, {candidate.url}"
    return reference.strip().rstrip(".") + "."


def _format_authors(authors: list[str]) -> str:
    normalized = [normalize_whitespace(author) for author in authors if normalize_whitespace(author)]
    if not normalized:
        return ""
    if len(normalized) == 1:
        return normalized[0]
    if len(normalized) == 2:
        return f"{normalized[0]} and {normalized[1]}"
    return f"{', '.join(normalized[:3])}, et al."
