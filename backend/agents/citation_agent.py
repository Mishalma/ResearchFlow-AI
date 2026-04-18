from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.config import Settings, get_settings
from citation.agent import run_citation_pipeline
from citation.config import CitationConfig
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import CitationAgentOutput, ResearchPaperSchema


class CitationAgent(BaseAgent):
    def __init__(
        self,
        mcp_server,
        spec: AgentSpec,
        settings: Settings | None = None,
    ):
        super().__init__(agent_name=spec.name, spec=spec)
        self.settings = settings or get_settings()
        self.citation_config = CitationConfig.from_settings(self.settings)

    async def process_task(self, message: A2AMessage) -> dict[str, Any]:
        payload = message.payload.get("paper", {})
        legacy_paper = ResearchPaperSchema.model_validate(payload)
        result = await run_citation_pipeline(
            written_draft=payload.get("written_draft"),
            structured_draft=payload.get("structured_draft"),
            paper_topic=str(message.payload.get("paper_topic", "")).strip() or None,
            paper_domain=str(message.payload.get("paper_domain", "")).strip() or None,
            author_metadata=message.payload.get("author_metadata"),
            trace_id=message.trace_id,
            settings=self.settings,
            config=self.citation_config,
            fallback_keywords=legacy_paper.keywords,
        )

        paper = result.paper_snapshot
        citation_draft = result.citation_draft
        if paper is None or citation_draft is None:
            raise ValueError("Citation runtime returned no paper snapshot.")

        output = CitationAgentOutput(
            title=paper.title,
            abstract=paper.abstract,
            keywords=legacy_paper.keywords or paper.keywords,
            sections=paper.sections,
            references=paper.references,
            citation_draft=citation_draft.model_dump(mode="python"),
            matched_claim_count=citation_draft.matched_claim_count,
            bibliography_count=citation_draft.bibliography_count,
            provider_summary=citation_draft.provider_summary,
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
