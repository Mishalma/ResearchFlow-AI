from __future__ import annotations

from textwrap import dedent

from agents.base import BaseAgent
from core.config import Settings, get_settings
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.generation import StructuringAgentOutput


class StructuringAgent(BaseAgent):
    def __init__(
        self,
        client: VertexGeminiClient,
        settings: Settings | None = None,
    ):
        super().__init__(agent_name="structuring_agent")
        self.client = client
        self.settings = settings or get_settings()

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        source_text = str(message.payload.get("raw_text", "")).strip()
        truncated_text = source_text[: self.settings.ai_source_text_max_chars]
        prompt = dedent(
            f"""
            You are the Structuring Agent for a research paper generator.
            Convert the source material into concise academic sections.

            Rules:
            - Use only information explicitly present in the source text.
            - Do not invent facts, results, citations, or datasets.
            - If a section is underspecified, acknowledge the limitation briefly instead of hallucinating.
            - Return output that matches the provided JSON response schema.

            Source text:
            {truncated_text}
            """
        ).strip()
        result = await self.client.generate_json(
            prompt=prompt,
            response_schema=StructuringAgentOutput,
        )
        return result.model_dump()
