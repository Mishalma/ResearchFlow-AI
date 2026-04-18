from __future__ import annotations

from dataclasses import replace

from agents.base import BaseAgent
from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import StructuringAgentOutput
from structuring.agent import run_structuring_pipeline
from structuring.config import StructuringConfig


class StructuringAgent(BaseAgent):
    def __init__(
        self,
        client: VertexGeminiClient,
        spec: AgentSpec,
        settings: Settings | None = None,
    ):
        super().__init__(agent_name=spec.name, spec=spec)
        self.client = client
        self.settings = settings or get_settings()
        base_config = StructuringConfig.from_settings(self.settings)
        self.structuring_config = replace(
            base_config,
            reducer_model=spec.model or base_config.reducer_model,
        )

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        result = await run_structuring_pipeline(
            source_text=str(message.payload.get("raw_text", "")),
            paper_topic=str(message.payload.get("paper_topic", "")).strip() or None,
            paper_domain=str(message.payload.get("paper_domain", "")).strip() or None,
            author_metadata=message.payload.get("author_metadata"),
            max_input_chars=message.payload.get("max_input_chars"),
            trace_id=message.trace_id,
            settings=self.settings,
            config=self.structuring_config,
            vertex_client=self.client,
        )
        paper = result.paper_snapshot
        structured_draft = result.structured_draft
        if paper is None or structured_draft is None:
            raise ValueError("Structuring runtime returned no paper snapshot.")

        output = StructuringAgentOutput(
            title=paper.title,
            abstract=paper.abstract,
            keywords=paper.keywords,
            sections=paper.sections,
            references=paper.references,
            structured_draft=structured_draft.model_dump(mode="python"),
            global_confidence=structured_draft.global_confidence,
            section_confidences={
                section_name: section.confidence
                for section_name, section in structured_draft.sections.items()
            },
            evidence_summary={
                section_name: len(section.source_spans)
                for section_name, section in structured_draft.sections.items()
            },
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
