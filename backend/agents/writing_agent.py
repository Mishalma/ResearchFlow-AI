from __future__ import annotations

from agents.base import BaseAgent
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import ResearchPaperSchema, WritingAgentOutput


class WritingAgent(BaseAgent):
    def __init__(self, client: VertexGeminiClient, spec: AgentSpec):
        super().__init__(agent_name=spec.name, spec=spec)
        self.client = client

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        paper = ResearchPaperSchema.model_validate(message.payload.get("paper", {}))
        validation_feedback = message.payload.get("validation_feedback", [])
        feedback_block = (
            "\n".join(f"- {item}" for item in validation_feedback)
            if validation_feedback
            else "- No validation issues were supplied."
        )
        prompt = self.render_prompt(
            paper_json=paper.model_dump_json(indent=2),
            validation_feedback=feedback_block,
        )
        result = await self.client.generate_json(
            prompt=prompt,
            response_schema=WritingAgentOutput,
            model_name=self.spec.model,
        )
        return result.model_dump()
