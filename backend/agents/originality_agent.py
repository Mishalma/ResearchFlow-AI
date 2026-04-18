from __future__ import annotations

from agents.base import BaseAgent
from core.config import get_settings
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import GeneratedPaper, HumanizerAgentOutput, OriginalityAgentOutput
from originality.agent import run_originality_pipeline
from originality.config import OriginalityConfig


class OriginalityAgent(BaseAgent):
    def __init__(self, spec: AgentSpec):
        super().__init__(agent_name=spec.name, spec=spec)
        self.settings = get_settings()
        self.originality_config = OriginalityConfig.from_settings(self.settings)

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        payload = message.payload.get("paper", {})
        humanizer_output = HumanizerAgentOutput.model_validate(payload)
        paper_snapshot = GeneratedPaper(
            paper=humanizer_output.paper,
            formatted_text=humanizer_output.formatted_text,
            latex_ready=humanizer_output.latex_ready,
        )
        result = await run_originality_pipeline(
            paper_snapshot=paper_snapshot,
            humanized_draft=humanizer_output.humanized_draft or message.payload.get("humanized_draft"),
            humanizer_ai_score=humanizer_output.ai_pattern_score_after,
            humanizer_graph_action=humanizer_output.graph_action,
            citation_draft=message.payload.get("citation_draft"),
            author_metadata=message.payload.get("author_metadata"),
            trace_id=message.trace_id,
            settings=self.settings,
            config=self.originality_config,
        )

        output = OriginalityAgentOutput(
            approved_snapshot=result.approved_snapshot,
            originality_report=result.originality_report.model_dump(mode="python")
            if result.originality_report is not None
            else None,
            provider_used=result.metadata.get("provider_used"),
            global_originality_score=(
                result.originality_report.global_originality_score
                if result.originality_report is not None
                else None
            ),
            global_ai_score=(
                result.originality_report.global_ai_score
                if result.originality_report is not None
                else humanizer_output.ai_pattern_score_after
            ),
            section_status_counts=result.metadata.get("section_status_counts", {}),
            decision_graph_action=(
                result.originality_report.decision.graph_action
                if result.originality_report is not None
                else None
            ),
            approved=result.approved_snapshot is not None,
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
