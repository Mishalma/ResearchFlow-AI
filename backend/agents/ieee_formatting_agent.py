from __future__ import annotations

from agents.base import BaseAgent
from app.services.paper_service import build_editor_display_text, build_latex_ready_text
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import FormattingAgentOutput, ResearchPaperSchema


class IEEEFormattingAgent(BaseAgent):
    def __init__(self, spec: AgentSpec):
        super().__init__(agent_name=spec.name, spec=spec)

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        paper = ResearchPaperSchema.model_validate(message.payload.get("paper", {}))
        output = FormattingAgentOutput(
            paper=paper,
            formatted_text=build_editor_display_text(paper),
            latex_ready=build_latex_ready_text(paper),
        )
        return output.model_dump()
