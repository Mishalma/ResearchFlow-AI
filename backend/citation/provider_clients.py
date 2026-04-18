from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from citation.config import CitationConfig
from citation.schemas import ProviderCandidate
from citation.utils import extract_doi, normalize_doi, normalize_whitespace

logger = logging.getLogger("papereasy.backend.citation.providers")


class ProviderClientError(RuntimeError):
    """Raised when a provider request cannot be completed successfully."""


class BaseHTTPProviderClient:
    def __init__(self, config: CitationConfig):
        self.config = config

    async def _request_json(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_json_sync,
            url=url,
            params=params,
            headers=headers,
            method=method,
            payload=payload,
        )

    async def _request_text(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._request_text_sync,
            url=url,
            params=params,
            headers=headers,
            method=method,
            payload=payload,
        )

    def _request_json_sync(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response_text = self._request_text_sync(
            url=url,
            params=params,
            headers={**(headers or {}), "Accept": "application/json"},
            method=method,
            payload=payload,
        )
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ProviderClientError(f"Invalid JSON response from {url}") from exc

    def _request_text_sync(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> str:
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value not in (None, "")},
            doseq=True,
        )
        full_url = f"{url}?{query}" if query else url
        data = None
        request_headers = {"User-Agent": "PaperEasyCitationAgent/1.0", **(headers or {})}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = urllib.request.Request(
            full_url,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.http_timeout_seconds) as response:
                charset = response.headers.get_content_charset("utf-8")
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderClientError(f"{method} {full_url} failed with status {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise ProviderClientError(f"{method} {full_url} failed: {exc.reason}") from exc


class SemanticScholarClient(BaseHTTPProviderClient):
    async def search_papers(self, *, query: str, limit: int) -> list[ProviderCandidate]:
        params = {
            "query": query,
            "limit": limit,
            "fields": ",".join(
                [
                    "paperId",
                    "title",
                    "abstract",
                    "authors",
                    "year",
                    "venue",
                    "externalIds",
                    "url",
                    "publicationTypes",
                    "citationCount",
                ]
            ),
        }
        headers = {}
        if self.config.semantic_scholar_api_key:
            headers["x-api-key"] = self.config.semantic_scholar_api_key

        payload = await self._request_json(
            url=f"{self.config.semantic_scholar_base_url}/paper/search",
            params=params,
            headers=headers,
        )
        results: list[ProviderCandidate] = []
        for index, item in enumerate(payload.get("data", []), start=1):
            paper_id = str(item.get("paperId", "")).strip()
            title = normalize_whitespace(item.get("title"))
            if not paper_id or not title:
                continue
            external_ids = item.get("externalIds") or {}
            doi = normalize_doi(external_ids.get("DOI")) or extract_doi(item.get("url"))
            results.append(
                ProviderCandidate(
                    candidate_id=f"semantic_scholar:{paper_id}",
                    provider="semantic_scholar",
                    provider_id=paper_id,
                    title=title,
                    authors=[normalize_whitespace(author.get("name")) for author in item.get("authors", []) if normalize_whitespace(author.get("name"))],
                    year=item.get("year"),
                    venue=normalize_whitespace(item.get("venue")),
                    abstract=normalize_whitespace(item.get("abstract")),
                    doi=doi,
                    url=item.get("url"),
                    source_query=query,
                    publication_types=[normalize_whitespace(value) for value in item.get("publicationTypes", []) if normalize_whitespace(value)],
                    citation_count=item.get("citationCount"),
                    external_ids={str(key): str(value) for key, value in external_ids.items() if str(value).strip()},
                    metadata={"provider_rank": index},
                )
            )
        return results

    async def fetch_papers_batch(self, *, paper_ids: list[str]) -> dict[str, ProviderCandidate]:
        if not paper_ids:
            return {}
        headers = {}
        if self.config.semantic_scholar_api_key:
            headers["x-api-key"] = self.config.semantic_scholar_api_key
        payload = await self._request_json(
            url=f"{self.config.semantic_scholar_base_url}/paper/batch",
            params={
                "fields": ",".join(
                    [
                        "paperId",
                        "title",
                        "abstract",
                        "authors",
                        "year",
                        "venue",
                        "externalIds",
                        "url",
                        "publicationTypes",
                        "citationCount",
                    ]
                )
            },
            headers=headers,
            method="POST",
            payload={"ids": paper_ids},
        )
        records: dict[str, ProviderCandidate] = {}
        for item in payload:
            paper_id = str(item.get("paperId", "")).strip()
            title = normalize_whitespace(item.get("title"))
            if not paper_id or not title:
                continue
            external_ids = item.get("externalIds") or {}
            records[paper_id] = ProviderCandidate(
                candidate_id=f"semantic_scholar:{paper_id}",
                provider="semantic_scholar",
                provider_id=paper_id,
                title=title,
                authors=[normalize_whitespace(author.get("name")) for author in item.get("authors", []) if normalize_whitespace(author.get("name"))],
                year=item.get("year"),
                venue=normalize_whitespace(item.get("venue")),
                abstract=normalize_whitespace(item.get("abstract")),
                doi=normalize_doi(external_ids.get("DOI")) or extract_doi(item.get("url")),
                url=item.get("url"),
                publication_types=[normalize_whitespace(value) for value in item.get("publicationTypes", []) if normalize_whitespace(value)],
                citation_count=item.get("citationCount"),
                external_ids={str(key): str(value) for key, value in external_ids.items() if str(value).strip()},
            )
        return records


class OpenAlexClient(BaseHTTPProviderClient):
    async def search_works(self, *, query: str, limit: int) -> list[ProviderCandidate]:
        params = {
            "search": query,
            "per-page": limit,
            "mailto": self.config.openalex_mailto,
        }
        if self.config.openalex_api_key:
            params["api_key"] = self.config.openalex_api_key

        payload = await self._request_json(
            url=f"{self.config.openalex_base_url}/works",
            params=params,
        )
        results: list[ProviderCandidate] = []
        for index, item in enumerate(payload.get("results", []), start=1):
            openalex_id = str(item.get("id", "")).strip()
            title = normalize_whitespace(item.get("title"))
            if not openalex_id or not title:
                continue
            doi = normalize_doi(item.get("doi"))
            if doi is None:
                doi = normalize_doi((item.get("ids") or {}).get("doi"))
            results.append(
                ProviderCandidate(
                    candidate_id=f"openalex:{openalex_id}",
                    provider="openalex",
                    provider_id=openalex_id,
                    title=title,
                    authors=[
                        normalize_whitespace((authorship.get("author") or {}).get("display_name"))
                        for authorship in item.get("authorships", [])
                        if normalize_whitespace((authorship.get("author") or {}).get("display_name"))
                    ],
                    year=item.get("publication_year"),
                    venue=normalize_whitespace(((item.get("primary_location") or {}).get("source") or {}).get("display_name")),
                    abstract=_openalex_abstract_to_text(item.get("abstract_inverted_index")),
                    doi=doi,
                    url=(item.get("primary_location") or {}).get("landing_page_url") or item.get("id"),
                    source_query=query,
                    publication_types=[normalize_whitespace(item.get("type"))] if normalize_whitespace(item.get("type")) else [],
                    citation_count=item.get("cited_by_count"),
                    external_ids={str(key): str(value) for key, value in (item.get("ids") or {}).items() if str(value).strip()},
                    metadata={"provider_rank": index},
                )
            )
        return results


class PubMedClient(BaseHTTPProviderClient):
    async def search_articles(self, *, query: str, limit: int) -> list[ProviderCandidate]:
        esearch_payload = await self._request_json(
            url=f"{self.config.ncbi_base_url}/esearch.fcgi",
            params={
                "db": "pubmed",
                "retmode": "json",
                "retmax": limit,
                "term": query,
                "api_key": self.config.ncbi_api_key,
                "tool": self.config.ncbi_tool,
                "email": self.config.ncbi_email,
            },
        )
        ids = [str(value).strip() for value in (esearch_payload.get("esearchresult") or {}).get("idlist", []) if str(value).strip()]
        if not ids:
            return []

        esummary_payload = await self._request_json(
            url=f"{self.config.ncbi_base_url}/esummary.fcgi",
            params={
                "db": "pubmed",
                "retmode": "json",
                "id": ",".join(ids),
                "api_key": self.config.ncbi_api_key,
                "tool": self.config.ncbi_tool,
                "email": self.config.ncbi_email,
            },
        )
        abstracts = await self._fetch_abstracts(ids)
        result_map = esummary_payload.get("result") or {}
        results: list[ProviderCandidate] = []
        for index, pmid in enumerate(ids, start=1):
            item = result_map.get(pmid) or {}
            title = normalize_whitespace(item.get("title"))
            if not title:
                continue
            authors = [
                normalize_whitespace(author.get("name"))
                for author in item.get("authors", [])
                if normalize_whitespace(author.get("name"))
            ]
            year_value = None
            pubdate = str(item.get("pubdate", "")).strip()
            if pubdate[:4].isdigit():
                year_value = int(pubdate[:4])
            results.append(
                ProviderCandidate(
                    candidate_id=f"pubmed:{pmid}",
                    provider="pubmed",
                    provider_id=pmid,
                    title=title,
                    authors=authors,
                    year=year_value,
                    venue=normalize_whitespace(item.get("fulljournalname") or item.get("source")),
                    abstract=normalize_whitespace(abstracts.get(pmid)),
                    doi=extract_doi(" ".join(str(article_id) for article_id in item.get("articleids", []))),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    source_query=query,
                    publication_types=[normalize_whitespace(value) for value in item.get("pubtype", []) if normalize_whitespace(value)],
                    citation_count=None,
                    external_ids={"pmid": pmid},
                    metadata={"provider_rank": index},
                )
            )
        return results

    async def _fetch_abstracts(self, pmids: list[str]) -> dict[str, str]:
        xml_text = await self._request_text(
            url=f"{self.config.ncbi_base_url}/efetch.fcgi",
            params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
                "api_key": self.config.ncbi_api_key,
                "tool": self.config.ncbi_tool,
                "email": self.config.ncbi_email,
            },
            headers={"Accept": "application/xml"},
        )
        root = ET.fromstring(xml_text)
        abstracts: dict[str, str] = {}
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID", default="").strip()
            if not pmid:
                continue
            abstract_fragments = [
                normalize_whitespace(text_node.text)
                for text_node in article.findall(".//Abstract/AbstractText")
                if normalize_whitespace(text_node.text)
            ]
            if abstract_fragments:
                abstracts[pmid] = " ".join(abstract_fragments)
        return abstracts


def _openalex_abstract_to_text(inverted_index: dict[str, list[int]] | None) -> str | None:
    if not inverted_index:
        return None
    tokens: list[tuple[int, str]] = []
    for token, positions in inverted_index.items():
        for position in positions:
            tokens.append((int(position), token))
    if not tokens:
        return None
    tokens.sort(key=lambda item: item[0])
    return normalize_whitespace(" ".join(token for _, token in tokens))
