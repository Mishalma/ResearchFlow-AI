from __future__ import annotations

from agents.base import BaseAgent
from models.a2a import A2AMessage
from models.generation import CitationAgentOutput, FormattingAgentOutput


class FormattingAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_name="formatting_agent")

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        content = CitationAgentOutput.model_validate(message.payload)
        references_block = "\n".join(content.references) if content.references else "[1] References pending"
        formatted_paper = "\n\n".join(
            [
                "RESEARCH PAPER",
                "Abstract\n" + content.abstract,
                "I. Introduction\n" + content.introduction,
                "II. Methodology\n" + content.methodology,
                "III. Conclusion\n" + content.conclusion,
                "References\n" + references_block,
            ]
        )
        output = FormattingAgentOutput(
            abstract=content.abstract,
            introduction=content.introduction,
            methodology=content.methodology,
            conclusion=content.conclusion,
            references=content.references,
            citation_sources=content.citation_sources,
            formatted_paper=formatted_paper,
        )
        return output.model_dump()
