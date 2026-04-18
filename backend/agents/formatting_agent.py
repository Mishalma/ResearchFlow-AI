from __future__ import annotations

from agents.base import BaseAgent
from formatting.agent import run_formatting_pipeline
from formatting.config import FormattingConfig
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import FormattingAgentOutput, ResearchPaperSchema


class FormattingAgent(BaseAgent):
    def __init__(self, spec: AgentSpec):
        super().__init__(agent_name=spec.name, spec=spec)
        self.formatting_config = FormattingConfig.from_settings()

    async def process_task(self, message: A2AMessage) -> dict[str, object]:
        payload = message.payload.get("paper", {})
        cited_paper = ResearchPaperSchema.model_validate(payload)
        result = await run_formatting_pipeline(
            paper=cited_paper,
            author_metadata=message.payload.get("author_metadata"),
            paper_metadata=message.payload.get("paper_metadata"),
            figures=message.payload.get("figures"),
            tables=message.payload.get("tables"),
            trace_id=message.trace_id,
            config=self.formatting_config,
        )

        paper_snapshot = result.paper_snapshot
        if paper_snapshot is None:
            paper_snapshot = ResearchPaperSchema.model_validate(cited_paper)
            from app.services.paper_service import build_editor_display_text, build_latex_ready_text

            formatted_text = build_editor_display_text(paper_snapshot)
            latex_ready = build_latex_ready_text(paper_snapshot)
        else:
            formatted_text = paper_snapshot.formatted_text
            latex_ready = paper_snapshot.latex_ready

        output = FormattingAgentOutput(
            paper=cited_paper,
            formatted_text=formatted_text,
            latex_ready=latex_ready,
            formatted_paper=result.formatted_paper.model_dump(mode="python")
            if result.formatted_paper is not None
            else None,
            compile_success=(
                result.formatted_paper.compile_report.success
                if result.formatted_paper is not None
                else None
            ),
            retry_recommended=result.metadata.get("retry_recommended"),
            diagnostic_summary=result.metadata.get("diagnostic_summary", {}),
            trace_id=result.trace_id,
            error=result.error.model_dump(mode="python") if result.error is not None else None,
        )
        return output.model_dump(mode="python")
