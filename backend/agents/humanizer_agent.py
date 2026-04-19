from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from core.config import get_settings
from core.vertex_client import VertexGeminiClient
from humanizer.agent import HumanizerRuntimeAgent, build_humanizer_output, run_humanizer_pipeline
from humanizer.config import HUMANIZER_MODE, HumanizerConfig
from humanizer.utils import build_section_text_map
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import FormattingAgentOutput, HumanizerAgentOutput, ResearchPaperSchema


class HumanizerAgent(BaseAgent):
    def __init__(
        self,
        client: VertexGeminiClient,
        spec: AgentSpec,
    ):
        super().__init__(agent_name=spec.name, spec=spec)
        self.client = client
        self.settings = get_settings()
        self.humanizer_config = HumanizerConfig.from_settings(self.settings)
        self.runtime = HumanizerRuntimeAgent(
            config=self.humanizer_config,
            settings=self.settings,
        )
        self.logger.info(
            "Humanizer bridge initialized in mode=%s",
            self.humanizer_config.runtime_mode,
        )

    def run(
        self,
        section_map: dict[str, str],
        *,
        paper: ResearchPaperSchema,
        iteration: int = 0,
    ) -> dict[str, Any]:
        result = self.runtime.run(section_map, iteration=iteration)
        self.logger.info(
            {
                "event": "humanizer_run",
                "iteration": iteration,
                "mode": HUMANIZER_MODE,
                "effective_mode": self.humanizer_config.runtime_mode,
                "action": result.get("graph_action"),
                "composite_before": result.get("scores_before", {}).get("composite_score"),
                "composite_after": result.get("scores_after", {}).get("composite_score"),
            }
        )
        return result

    def build_output(
        self,
        *,
        paper: ResearchPaperSchema,
        runtime_result: dict[str, Any],
        trace_id: str | None = None,
    ) -> HumanizerAgentOutput:
        return build_humanizer_output(
            paper=paper,
            runtime_result=runtime_result,
            trace_id=trace_id,
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
        )
        if result.paper_snapshot is None or result.humanized_draft is None:
            raise ValueError("Humanizer runtime returned no paper snapshot.")

        output = HumanizerAgentOutput(
            paper=result.paper_snapshot.paper,
            formatted_text=result.paper_snapshot.formatted_text,
            latex_ready=result.paper_snapshot.latex_ready,
            humanized_draft=result.humanized_draft.model_dump(mode="python"),
            ai_pattern_score_before=result.humanized_draft.global_ai_pattern_score_before,
            ai_pattern_score_after=result.humanized_draft.global_ai_pattern_score_after,
            perplexity_before=result.humanized_draft.global_perplexity_before,
            perplexity_after=result.humanized_draft.global_perplexity_after,
            iteration_count=int(result.metadata.get("iteration", 0)),
            graph_action=result.humanized_draft.graph_action,
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
