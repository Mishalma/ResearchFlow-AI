from __future__ import annotations

from typing import Any


def _format_authors(authors: list[str]) -> str:
    if not authors:
        return "Unknown Author"

    if len(authors) == 1:
        return authors[0]

    return ", ".join(authors[:-1]) + ", and " + authors[-1]


def citation_tool(payload: dict[str, Any]) -> dict[str, Any]:
    reference = dict(payload.get("reference", {}))
    index = int(payload.get("index", 1))
    title = str(reference.get("title", "Untitled Reference")).strip()
    authors = list(reference.get("authors", []))
    year = int(reference.get("year", 2024))
    source = str(reference.get("source", "Simulated MCP Citation Service")).strip()
    query = str(payload.get("query", reference.get("query", "general research"))).strip()

    ieee_reference = (
        f"[{index}] {_format_authors(authors)}, \"{title},\" {source}, {year}."
    )
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "source": source,
        "query": query or "general research",
        "ieee_reference": ieee_reference,
    }
