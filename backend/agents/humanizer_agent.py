from __future__ import annotations

from dataclasses import replace
from typing import Any

from agents.base import BaseAgent
from core.config import get_settings
from core.vertex_client import VertexGeminiClient
from humanizer.agent import run_humanizer_pipeline
from humanizer.config import HumanizerConfig
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import FormattingAgentOutput, HumanizerAgentOutput


class HumanizerAgent(BaseAgent):
    def __init__(
        self,
        client: VertexGeminiClient,
        spec: AgentSpec,
    ):
        super().__init__(agent_name=spec.name, spec=spec)
        self.client = client
        self.settings = get_settings()
        base_config = HumanizerConfig.from_settings(self.settings)
        self.humanizer_config = replace(
            base_config,
            rewriter_model=spec.model or base_config.rewriter_model,
        )

    async def process_task(self, message: A2AMessage) -> dict[str, Any]:
        payload = message.payload.get("paper", {})
        formatting_output = FormattingAgentOutput.model_validate(payload)
        result = await run_humanizer_pipeline(
            paper=formatting_output.paper,
            formatted_text=formatting_output.formatted_text,
            latex_ready=formatting_output.latex_ready,
            written_draft=message.payload.get("written_draft"),
            section_confidences=message.payload.get("section_confidences"),
            trace_id=message.trace_id,
            settings=self.settings,
            config=self.humanizer_config,
            vertex_client=self.client,
        )

        paper_snapshot = result.paper_snapshot
        humanized_draft = result.humanized_draft
        if paper_snapshot is None or humanized_draft is None:
            raise ValueError("Humanizer runtime returned no paper snapshot.")

        output = HumanizerAgentOutput(
            paper=paper_snapshot.paper,
            formatted_text=paper_snapshot.formatted_text,
            latex_ready=paper_snapshot.latex_ready,
            humanized_draft=humanized_draft.model_dump(mode="python"),
            ai_pattern_score_before=humanized_draft.global_ai_pattern_score_before,
            ai_pattern_score_after=humanized_draft.global_ai_pattern_score_after,
            perplexity_before=humanized_draft.global_perplexity_before,
            perplexity_after=humanized_draft.global_perplexity_after,
            iteration_count=int(humanized_draft.metadata.get("iteration_count", 0)),
            graph_action=humanized_draft.graph_action,
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
