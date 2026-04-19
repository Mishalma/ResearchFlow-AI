from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from core.config import get_settings
from core.vertex_client import VertexGeminiClient
from figure_table.models import FigureTableOutput
from figure_table.runtime import FigureTableRuntime
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import FigureTableAgentOutput, ResearchPaperSchema, WritingAgentOutput


class FigureTableAgent(BaseAgent):
    def __init__(self, client: VertexGeminiClient, spec: AgentSpec, mcp_server=None):
        super().__init__(agent_name=spec.name, spec=spec)
        self.client = client
        self.mcp_server = mcp_server
        self.settings = get_settings()
        self.runtime = FigureTableRuntime(gemini_client=client, settings=self.settings)

    async def run(
        self,
        writing_output: WritingAgentOutput,
        project_id: str,
    ) -> FigureTableAgentOutput:
        result = await self.runtime.execute(
            written_draft=writing_output.written_draft,
            gemini_client=self.client,
            project_id=project_id,
            paper_snapshot=ResearchPaperSchema.model_validate(writing_output.model_dump(mode="python")),
        )
        return FigureTableAgentOutput.model_validate(result.model_dump(mode="python"))

    async def process_task(self, message: A2AMessage) -> dict[str, Any]:
        payload = message.payload.get("paper", {})
        writing_output = WritingAgentOutput.model_validate(payload)
        project_id = str(message.payload.get("project_id", "")).strip()
        result = await self.run(
            writing_output=writing_output,
            project_id=project_id,
        )
        return result.model_dump(mode="python")
