from __future__ import annotations

from textwrap import dedent

from agents.base import BaseAgent
from core.vertex_client import VertexGeminiClient
from models.a2a import A2AMessage
from models.generation import PaperSections, WritingAgentOutput


class WritingAgent(BaseAgent):
    def __init__(self, client: VertexGeminiClient):
        super().__init__(agent_name="writing_agent")
        self.client = client

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        sections = PaperSections.model_validate(message.payload.get("sections", {}))
        prompt = dedent(
            f"""
            You are the Writing Agent for an academic paper generator.
            Improve clarity, coherence, and academic tone while preserving the original meaning.

            Rules:
            - Preserve the source intent and section boundaries.
            - Do not add unsupported claims, citations, datasets, or results.
            - Tighten wording and improve transitions.
            - Return output that matches the provided JSON response schema.

            Input sections:
            {sections.model_dump_json(indent=2)}
            """
        ).strip()
        result = await self.client.generate_json(
            prompt=prompt,
            response_schema=WritingAgentOutput,
        )
        return result.model_dump()
