from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.config import Settings, get_settings
from mcp.mcp_server import MCPServer
from models.a2a import A2AMessage
from models.generation import CitationAgentOutput, CitationSource, PaperSections


class CitationAgent(BaseAgent):
    def __init__(self, mcp_server: MCPServer, settings: Settings | None = None):
        super().__init__(agent_name="citation_agent")
        self.mcp_server = mcp_server
        self.settings = settings or get_settings()

    async def process_task(self, message: A2AMessage) -> dict[str, Any]:
        sections = PaperSections.model_validate(message.payload.get("sections", {}))
        queries = self._build_queries(sections)
        formatted_references: list[str] = []
        citation_sources: list[CitationSource] = []
        seen_titles: set[str] = set()

        for query in queries:
            remaining = self.settings.citation_result_limit - len(formatted_references)
            if remaining <= 0:
                break

            search_results = await self.mcp_server.call_tool(
                "search_tool",
                {"query": query, "limit": remaining},
            )
            for result in search_results:
                title = str(result.get("title", "")).strip().lower()
                if not title or title in seen_titles:
                    continue

                citation = await self.mcp_server.call_tool(
                    "citation_tool",
                    {
                        "reference": result,
                        "index": len(formatted_references) + 1,
                        "query": query,
                    },
                )
                formatted_references.append(citation["ieee_reference"])
                citation_sources.append(CitationSource.model_validate(citation))
                seen_titles.add(title)

                if len(formatted_references) >= self.settings.citation_result_limit:
                    break

        output = CitationAgentOutput(
            abstract=sections.abstract,
            introduction=sections.introduction,
            methodology=sections.methodology,
            conclusion=sections.conclusion,
            references=formatted_references,
            citation_sources=citation_sources,
        )
        return output.model_dump()

    def _build_queries(self, sections: PaperSections) -> list[str]:
        candidates = [
            sections.introduction,
            sections.methodology,
            sections.conclusion,
        ]
        queries: list[str] = []
        for text in candidates:
            normalized = " ".join(text.split())
            if not normalized:
                continue
            queries.append(normalized[:120])

        return queries[:3]
