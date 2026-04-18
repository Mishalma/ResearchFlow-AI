from __future__ import annotations

import logging
import urllib.parse

from citation.config import CitationConfig
from citation.provider_clients import BaseHTTPProviderClient
from citation.schemas import ProviderCandidate
from citation.utils import merge_dicts, normalize_doi, normalize_whitespace

logger = logging.getLogger("papereasy.backend.citation.doi")


class DOIClient(BaseHTTPProviderClient):
    async def enrich_candidate(self, candidate: ProviderCandidate) -> ProviderCandidate:
        normalized_doi = normalize_doi(candidate.doi)
        if not normalized_doi:
            return candidate

        updates: dict[str, object] = {
            "doi": normalized_doi,
            "doi_status": "resolved",
        }
        try:
            csl_payload = await self._request_json(
                url=f"{self.config.doi_base_url}/{urllib.parse.quote(normalized_doi, safe='')}",
                headers={"Accept": "application/vnd.citationstyles.csl+json"},
            )
            updates = merge_dicts(
                updates,
                {
                    "title": normalize_whitespace(_extract_csl_title(csl_payload)) or candidate.title,
                    "authors": _extract_csl_authors(csl_payload) or candidate.authors,
                    "year": _extract_csl_year(csl_payload) or candidate.year,
                    "venue": normalize_whitespace(csl_payload.get("container-title")) or candidate.venue,
                    "url": csl_payload.get("URL") or candidate.url,
                    "metadata": merge_dicts(candidate.metadata, {"doi_csl": csl_payload}),
                },
            )
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("DOI CSL-JSON lookup failed for %s: %s", normalized_doi, exc)
            updates["doi_status"] = "resolution_failed"

        try:
            bibliography_text = await self._request_text(
                url=f"{self.config.doi_base_url}/{urllib.parse.quote(normalized_doi, safe='')}",
                headers={"Accept": "text/x-bibliography; style=ieee"},
            )
            formatted = normalize_whitespace(bibliography_text)
            if formatted:
                updates["ieee_reference"] = formatted
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("DOI bibliography lookup failed for %s: %s", normalized_doi, exc)

        if self.config.enable_crossref_enrichment:
            try:
                crossref_payload = await self._request_json(
                    url=f"{self.config.crossref_base_url}/works/{urllib.parse.quote(normalized_doi, safe='')}",
                    params={"mailto": self.config.crossref_mailto},
                )
                message = crossref_payload.get("message") or {}
                updates["metadata"] = merge_dicts(candidate.metadata, {"crossref": message})
                if not updates.get("venue"):
                    titles = message.get("container-title") or []
                    if titles:
                        updates["venue"] = normalize_whitespace(titles[0])
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Crossref enrichment failed for %s: %s", normalized_doi, exc)

        return candidate.model_copy(update=updates)


def _extract_csl_title(payload: dict) -> str:
    title = payload.get("title")
    if isinstance(title, list):
        return normalize_whitespace(title[0]) if title else ""
    return normalize_whitespace(title)


def _extract_csl_authors(payload: dict) -> list[str]:
    authors: list[str] = []
    for author in payload.get("author", []):
        family = normalize_whitespace(author.get("family"))
        given = normalize_whitespace(author.get("given"))
        if family and given:
            authors.append(f"{given} {family}")
        elif family:
            authors.append(family)
    return authors


def _extract_csl_year(payload: dict) -> int | None:
    issued = payload.get("issued") or {}
    parts = issued.get("date-parts") or []
    if not parts or not parts[0]:
        return None
    try:
        return int(parts[0][0])
    except (TypeError, ValueError):
        return None
