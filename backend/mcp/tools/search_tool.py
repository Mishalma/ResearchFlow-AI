from __future__ import annotations

from typing import Any

SIMULATED_AUTHORS = [
    ["A. Sharma", "L. Chen"],
    ["M. Patel", "R. Gomez"],
    ["J. Kim", "P. Singh"],
]

SIMULATED_SUFFIXES = [
    "A Systematic Review",
    "An Applied Framework",
    "Methods and Evaluation",
]


def search_tool(payload: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(payload.get("query", "")).strip()
    if not query:
        return []

    limit = max(1, int(payload.get("limit", len(SIMULATED_SUFFIXES))))
    base_title = query[:60].strip().rstrip(".,")
    results: list[dict[str, Any]] = []
    for index, suffix in enumerate(SIMULATED_SUFFIXES[:limit], start=1):
        results.append(
            {
                "title": f"{base_title}: {suffix}",
                "authors": SIMULATED_AUTHORS[index - 1],
                "year": 2021 + index,
                "source": "Simulated MCP Research Index",
                "query": query,
            }
        )

    return results
