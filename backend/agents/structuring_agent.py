from __future__ import annotations

from agents.base import BaseAgent
from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import StructuringAgentOutput


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

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        source_text = str(message.payload.get("raw_text", "")).strip()
        truncated_text = source_text[: self.settings.ai_source_text_max_chars]
        validation_feedback = message.payload.get("validation_feedback", [])
        feedback_block = (
            "\n".join(f"- {item}" for item in validation_feedback)
            if validation_feedback
            else "- No validation issues were supplied."
        )
        prompt = self.render_prompt(
            source_text=truncated_text,
            validation_feedback=feedback_block,
        )
        result = await self.client.generate_json(
            prompt=prompt,
            response_schema=StructuringAgentOutput,
            model_name=self.spec.model,
        )
        return result.model_dump()
