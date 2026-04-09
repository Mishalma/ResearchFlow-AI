from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.config import Settings, get_settings
from mcp.mcp_server import MCPServer
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import CitationAgentOutput, ResearchPaperSchema


class CitationAgent(BaseAgent):
    def __init__(
        self,
        mcp_server: MCPServer,
        spec: AgentSpec,
        settings: Settings | None = None,
    ):
        super().__init__(agent_name=spec.name, spec=spec)
        self.mcp_server = mcp_server
        self.settings = settings or get_settings()

    async def process_task(self, message: A2AMessage) -> dict[str, Any]:
        paper = ResearchPaperSchema.model_validate(message.payload.get("paper", {}))
        queries = self._build_queries(paper)
        formatted_references: list[str] = []
        seen_titles: set[str] = set()

        search_tool_name = self.spec.enabled_tools[0] if self.spec.enabled_tools else "search_tool"
        citation_tool_name = self.spec.enabled_tools[1] if len(self.spec.enabled_tools) > 1 else "citation_tool"

        for query in queries:
            remaining = self.settings.citation_result_limit - len(formatted_references)
            if remaining <= 0:
                break

            search_results = await self.mcp_server.call_tool(
                search_tool_name,
                {"query": query, "limit": remaining},
            )
            for result in search_results:
                title = str(result.get("title", "")).strip().lower()
                if not title or title in seen_titles:
                    continue

                citation = await self.mcp_server.call_tool(
                    citation_tool_name,
                    {
                        "reference": result,
                        "index": len(formatted_references) + 1,
                        "query": query,
                    },
                )
                formatted_references.append(str(citation["ieee_reference"]).strip())
                seen_titles.add(title)

                if len(formatted_references) >= self.settings.citation_result_limit:
                    break

        if not formatted_references:
            formatted_references.append(
                "[1] PaperEasy Citation Agent, \"Reference enrichment pending manual review,\" Internal Research Workflow, 2026."
            )

        output = CitationAgentOutput(
            title=paper.title,
            abstract=paper.abstract,
            keywords=paper.keywords,
            sections=paper.sections,
            references=formatted_references,
        )
        return output.model_dump()

    def _build_queries(self, paper: ResearchPaperSchema) -> list[str]:
        candidates = [
            paper.title,
            paper.sections.introduction,
            paper.sections.methodology,
            paper.sections.results,
            paper.sections.discussion,
        ]
        queries: list[str] = []
        for text in candidates:
            normalized = " ".join(text.split())
            if not normalized:
                continue
            queries.append(normalized[:120])

        return queries[:4]
