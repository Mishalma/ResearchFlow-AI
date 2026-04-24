from __future__ import annotations

import logging
import os
import re
from dataclasses import replace

from humanizer.agent import HumanizerRuntimeAgent
from humanizer.config import HumanizerConfig
from humanizer.utils import build_generated_paper, build_section_text_map
from jobs.artifacts import (
    load_generated_draft_artifact,
    load_validation_report_artifact,
    store_generated_draft_artifact,
)
from models.fix import FixSectionTarget, FixServiceRequest, FixServiceResponse
from models.validation import ValidationSectionFlag
from core.config import Settings, get_settings

logger = logging.getLogger("papereasy.fix.runtime")


def _resolve_humanizer_config(settings: Settings) -> HumanizerConfig:
    config = HumanizerConfig.from_settings(settings)
    use_model_rewriter = config.use_model_rewriter
    enable_perplexity = config.enable_perplexity
    if "HUMANIZER_USE_MODEL_REWRITER" not in os.environ:
        use_model_rewriter = False
    if "HUMANIZER_ENABLE_PERPLEXITY" not in os.environ:
        enable_perplexity = False
    return replace(
        config,
        use_model_rewriter=use_model_rewriter,
        enable_perplexity=enable_perplexity,
    )


def _next_draft_version(current_draft_uri: str) -> str:
    match = re.search(r"draft_v(\d+)\.json$", str(current_draft_uri or ""))
    if not match:
        return "draft_v2"
    next_version = int(match.group(1)) + 1
    if next_version > 5:
        raise ValueError("Fix loop exceeded the supported immutable draft versions.")
    return f"draft_v{next_version}"


def _load_section_targets(request: FixServiceRequest) -> list[FixSectionTarget]:
    if request.targets:
        return list(request.targets)

    payload = load_validation_report_artifact(request.validation_report_uri)
    raw_flags = payload.get("section_flags", [])
    targets: list[FixSectionTarget] = []
    for raw_flag in raw_flags:
        flag = ValidationSectionFlag.model_validate(raw_flag)
        if flag.flag_type != "ai" or flag.risk not in {"medium", "severe"}:
            continue
        targets.append(
            FixSectionTarget(
                section_id=flag.section_id,
                flag_type="ai",
                risk=flag.risk,
                score=min(1.0, float(flag.score)),
                summary=flag.summary,
            )
        )
    return targets


async def execute_fix_request(
    request: FixServiceRequest,
    *,
    settings: Settings | None = None,
) -> FixServiceResponse:
    resolved_settings = settings or get_settings()
    draft = load_generated_draft_artifact(request.current_draft_uri)
    targets = _load_section_targets(request)

    if not targets:
        fix_summary = {
            "attempted": False,
            "status": "not_needed",
            "iterations": request.iteration,
            "changed_sections": [],
            "rewriter_mode": None,
        }
        return FixServiceResponse(
            job_id=request.job_id,
            output={
                "mode": request.mode,
                "updated_draft_uri": request.current_draft_uri,
                "draft_artifact": None,
                "changed_sections": [],
                "rewriter_mode": None,
                "fix_status": "not_needed",
                "fix_summary": fix_summary,
            },
        )

    section_map = build_section_text_map(draft.paper)
    target_section_ids = {target.section_id for target in targets}
    runtime = HumanizerRuntimeAgent(
        config=_resolve_humanizer_config(resolved_settings),
        settings=resolved_settings,
    )
    runtime_result = runtime.run(
        section_map,
        iteration=request.iteration,
        target_sections=target_section_ids,
    )
    changed_sections = [
        section_id
        for section_id in target_section_ids
        if runtime_result["updated_sections"].get(section_id, "").strip()
        != section_map.get(section_id, "").strip()
    ]
    generated_paper = build_generated_paper(
        source_paper=draft.paper,
        section_texts=runtime_result["updated_sections"],
    )
    rewriter_mode = runtime_result.get("rewriter_mode")
    fix_status = "applied" if changed_sections else "failed"
    draft_artifact = store_generated_draft_artifact(
        request.project_id,
        request.job_id,
        version=_next_draft_version(request.current_draft_uri),
        generated_paper=generated_paper,
        owner_service="fix-service",
    )
    fix_summary = {
        "attempted": True,
        "status": fix_status,
        "iterations": request.iteration,
        "changed_sections": changed_sections,
        "rewriter_mode": rewriter_mode,
    }
    logger.info(
        "Fix request %s completed with status=%s changed_sections=%s mode=%s",
        request.job_id,
        fix_status,
        changed_sections,
        rewriter_mode,
    )
    return FixServiceResponse(
        job_id=request.job_id,
        output={
            "mode": request.mode,
            "updated_draft_uri": draft_artifact.uri,
            "draft_artifact": draft_artifact,
            "changed_sections": changed_sections,
            "rewriter_mode": rewriter_mode,
            "fix_status": fix_status,
            "fix_summary": fix_summary,
        },
    )
