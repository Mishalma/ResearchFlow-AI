from __future__ import annotations

from models.generation import PipelineResult
from orchestration.pipeline import run_pipeline


async def generate_structured_paper(
    source_text: str,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> PipelineResult:
    _ = provider_override
    _ = model_override
    return await run_pipeline(source_text)
