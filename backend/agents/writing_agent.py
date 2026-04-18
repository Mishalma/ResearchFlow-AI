from __future__ import annotations

from dataclasses import replace

from agents.base import BaseAgent
from core.config import get_settings
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import ResearchPaperSchema, WritingAgentOutput
from writing.agent import run_writing_pipeline
from writing.config import WritingConfig


class WritingAgent(BaseAgent):
    def __init__(self, client: VertexGeminiClient, spec: AgentSpec):
        super().__init__(agent_name=spec.name, spec=spec)
        self.client = client
        self.settings = get_settings()
        base_config = WritingConfig.from_settings(self.settings)
        self.writing_config = replace(
            base_config,
            reducer_model=spec.model or base_config.reducer_model,
        )

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        payload = message.payload.get("paper", {})
        legacy_paper = ResearchPaperSchema.model_validate(payload)
        result = await run_writing_pipeline(
            structured_draft=payload.get("structured_draft"),
            paper_topic=str(message.payload.get("paper_topic", "")).strip() or None,
            paper_domain=str(message.payload.get("paper_domain", "")).strip() or None,
            author_metadata=message.payload.get("author_metadata"),
            writing_style_preferences=message.payload.get("writing_style_preferences"),
            trace_id=message.trace_id,
            settings=self.settings,
            config=self.writing_config,
            vertex_client=self.client,
            fallback_keywords=legacy_paper.keywords,
            fallback_references=legacy_paper.references,
        )

        paper = result.paper_snapshot
        written_draft = result.written_draft
        if paper is None or written_draft is None:
            raise ValueError("Writing runtime returned no paper snapshot.")

        output = WritingAgentOutput(
            title=paper.title,
            abstract=paper.abstract,
            keywords=legacy_paper.keywords or paper.keywords,
            sections=paper.sections,
            references=legacy_paper.references or paper.references,
            written_draft=written_draft.model_dump(mode="python"),
            global_confidence=written_draft.global_confidence,
            section_confidences={
                "abstract": written_draft.abstract.confidence,
                **{
                    section_name: section.confidence
                    for section_name, section in written_draft.sections.items()
                },
            },
            annotation_summary=result.metadata.get("annotation_summary", {}),
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
