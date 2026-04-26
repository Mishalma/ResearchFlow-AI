"""Runtime entrypoint for the upgraded humanizer agent.

This module exposes a synchronous humanizer core used by the pipeline bridge,
an async compatibility wrapper for existing callers, and an optional guarded
ADK entrypoint.
"""

from __future__ import annotations

import logging
import os
from statistics import mean
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationError

from core.config import Settings, get_settings
from humanizer.config import (
    HUMANIZER_MODE,
    LOG_MODE_ON_EVERY_RUN,
    MAX_AI_PATTERN_SCORE_TO_PASS,
    MAX_ITERATIONS,
    MIN_BURSTINESS_TO_PASS,
    HumanizerConfig,
)
from humanizer.detectors import analyze_section, composite_ai_score
from humanizer.perplexity import PerplexityScorer
from humanizer.rewriter import HumanizerRewriter
from humanizer.schemas import (
    HumanizedPaperDraft,
    HumanizedSection,
    HumanizerAgentError,
    HumanizerAgentResult,
    ParagraphHumanizationReport,
    SectionHumanizationReport,
)
from humanizer.utils import (
    SECTION_ORDER,
    build_diff_summary,
    build_generated_paper,
    build_section_text_map,
)
from models.generation import GeneratedPaper, ResearchPaperSchema

logger = logging.getLogger(__name__)

try:  # pragma: no cover - environment dependent import
    from google.adk.agents import BaseAgent as ADKBaseAgent
    from google.adk.events import Event
    from google.genai import types

    ADK_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - environment dependent
    ADKBaseAgent = None
    Event = None
    types = None
    ADK_IMPORT_ERROR = exc


class HumanizerRuntimeAgent:
    """Synchronous multi-pass humanizer runtime."""

    def __init__(
        self,
        config: HumanizerConfig | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.config = config or HumanizerConfig.from_settings(self.settings)
        self.rewriter = HumanizerRewriter(self.config)
        self.perplexity = PerplexityScorer()
        if LOG_MODE_ON_EVERY_RUN or self.config.log_mode_on_every_run:
            logger.info("Humanizer runtime initialized in %s mode.", self.config.runtime_mode)

    def run(
        self,
        section_map: dict[str, str],
        iteration: int = 0,
        *,
        target_sections: set[str] | None = None,
        remediation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Humanize a section map and return scores plus orchestration metadata."""

        if LOG_MODE_ON_EVERY_RUN or self.config.log_mode_on_every_run:
            logger.info(
                "Humanizer run started in %s mode at iteration %s.",
                self.config.runtime_mode,
                iteration,
            )

        deadline = perf_counter() + max(5, int(self.config.max_runtime_seconds))
        updated_sections: dict[str, str] = {}
        scores_before_sections: dict[str, dict[str, float]] = {}
        scores_after_sections: dict[str, dict[str, float]] = {}
        run_log: list[str] = []
        perplexity_before_values: list[float] = []
        perplexity_after_values: list[float] = []
        sections_skipped = 0
        sections_rewritten = 0
        actual_modes: set[str] = set()
        failure_reasons: list[str] = []
        strategies_used: set[str] = set()
        candidate_count = 0
        accepted_candidate_count = 0
        best_candidate_ai_score: float | None = None
        best_candidate_overlap_score: float | None = None
        retry_recommended = False
        active_strategy = _strategy_for_iteration(iteration, self.config.strategy_order)
        targeted_sections = (
            {section_name.strip() for section_name in target_sections if str(section_name).strip()}
            if target_sections is not None
            else None
        )
        runtime_budget_exceeded = False

        for section_name in SECTION_ORDER:
            original_text = str(section_map.get(section_name, "") or "").strip()
            if perf_counter() >= deadline:
                runtime_budget_exceeded = True
                updated_sections[section_name] = original_text
                original_scores = composite_ai_score(original_text)
                scores_before_sections[section_name] = original_scores
                scores_after_sections[section_name] = original_scores
                sections_skipped += 1
                _append_unique(failure_reasons, "humanizer_runtime_budget_exceeded")
                run_log.append(f"{section_name}: skipped (humanizer runtime budget exceeded)")
                continue

            before_scores = composite_ai_score(original_text)
            scores_before_sections[section_name] = before_scores
            run_log.append(
                f"{section_name}: before composite={before_scores.get('composite_score', 0.0):.3f}, "
                f"burstiness={before_scores.get('burstiness', 0.0):.3f}"
            )

            if self.config.perplexity_enabled:
                before_perplexity = self.perplexity.score(original_text)
                if before_perplexity is not None:
                    perplexity_before_values.append(before_perplexity)

            if targeted_sections is not None and section_name not in targeted_sections:
                updated_sections[section_name] = original_text
                scores_after_sections[section_name] = before_scores
                sections_skipped += 1
                run_log.append(f"{section_name}: skipped (outside targeted fix scope)")
                continue

            externally_targeted = targeted_sections is not None and section_name in targeted_sections
            if (
                not externally_targeted
                and before_scores.get("composite_score", 0.0) <= self.config.max_ai_pattern_score_to_pass
                and before_scores.get("burstiness", 0.0) >= self.config.min_burstiness_to_pass
            ):
                updated_sections[section_name] = original_text
                scores_after_sections[section_name] = before_scores
                sections_skipped += 1
                run_log.append(f"{section_name}: pass without rewrite")
                continue

            if externally_targeted:
                run_log.append(f"{section_name}: targeted by validation detector")

            try:
                rewrite_result = self.rewriter.rewrite_section(
                    section_text=original_text,
                    ai_scores=before_scores,
                    style_persona=_style_persona(section_name),
                    section_name=section_name,
                    force_rewrite=externally_targeted,
                    require_quality_improvement=not externally_targeted,
                    remediation_context=remediation_context,
                    strategy=active_strategy if externally_targeted else None,
                )
            except TypeError as exc:
                if "remediation_context" not in str(exc) and "strategy" not in str(exc):
                    raise
                rewrite_result = self.rewriter.rewrite_section(
                    section_text=original_text,
                    ai_scores=before_scores,
                    style_persona=_style_persona(section_name),
                    section_name=section_name,
                    force_rewrite=externally_targeted,
                    require_quality_improvement=not externally_targeted,
                )
            rewritten_text = rewrite_result["rewritten_text"]
            after_scores = composite_ai_score(rewritten_text)
            scores_after_sections[section_name] = after_scores
            updated_sections[section_name] = rewritten_text
            if rewritten_text.strip() != original_text.strip():
                sections_rewritten += 1
            actual_modes.add(str(rewrite_result["rewriter_used"]))
            failure_reasons.extend(list(rewrite_result.get("failure_reasons", [])))
            if rewrite_result.get("strategy"):
                strategies_used.add(str(rewrite_result["strategy"]))
            candidate_count += int(rewrite_result.get("candidate_count") or 0)
            accepted_candidate_count += int(rewrite_result.get("accepted_candidate_count") or 0)
            candidate_ai_score = rewrite_result.get("best_candidate_ai_score")
            if candidate_ai_score is not None:
                candidate_score_value = float(candidate_ai_score)
                best_candidate_ai_score = (
                    candidate_score_value
                    if best_candidate_ai_score is None
                    else min(best_candidate_ai_score, candidate_score_value)
                )
            candidate_overlap_score = rewrite_result.get("best_candidate_overlap_score")
            if candidate_overlap_score is not None:
                candidate_overlap_value = float(candidate_overlap_score)
                best_candidate_overlap_score = (
                    candidate_overlap_value
                    if best_candidate_overlap_score is None
                    else min(best_candidate_overlap_score, candidate_overlap_value)
                )
            retry_recommended = retry_recommended or bool(rewrite_result.get("retry_recommended"))

            if self.config.perplexity_enabled:
                after_perplexity = self.perplexity.score(rewritten_text)
                if after_perplexity is not None:
                    perplexity_after_values.append(after_perplexity)

            run_log.append(
                f"{section_name}: after composite={after_scores.get('composite_score', 0.0):.3f}, "
                f"targeted={rewrite_result['paragraphs_targeted']}, "
                f"accepted={rewrite_result['paragraphs_accepted']}, "
                f"rejected_drift={rewrite_result['paragraphs_rejected_drift']}, "
                f"mode={rewrite_result['rewriter_used']}, "
                f"strategy={rewrite_result.get('strategy') or 'paragraph'}"
            )

        overall_before = max(
            (scores.get("composite_score", 0.0) for scores in scores_before_sections.values()),
            default=0.0,
        )
        overall_after = max(
            (scores.get("composite_score", 0.0) for scores in scores_after_sections.values()),
            default=0.0,
        )
        graph_action = _select_graph_action(
            composite_score=overall_after,
            iteration=iteration,
            max_iterations=self.config.max_iterations,
            runtime_budget_exceeded=runtime_budget_exceeded,
            sections_rewritten=sections_rewritten,
        )
        rewriter_mode = _resolve_rewriter_mode(actual_modes, self.config.resolved_mode)

        return {
            "updated_sections": updated_sections,
            "graph_action": graph_action,
            "scores_before": {
                "sections": scores_before_sections,
                "composite_score": round(overall_before, 4),
            },
            "scores_after": {
                "sections": scores_after_sections,
                "composite_score": round(overall_after, 4),
            },
            "perplexity_before": round(mean(perplexity_before_values), 4)
            if perplexity_before_values
            else None,
            "perplexity_after": round(mean(perplexity_after_values), 4)
            if perplexity_after_values
            else None,
            "iteration": iteration,
            "sections_skipped": sections_skipped,
            "sections_rewritten": sections_rewritten,
            "rewriter_mode": rewriter_mode,
            "failure_reasons": failure_reasons,
            "strategy": _resolve_strategy(strategies_used),
            "candidate_count": candidate_count,
            "accepted_candidate_count": accepted_candidate_count,
            "best_candidate_ai_score": best_candidate_ai_score,
            "best_candidate_overlap_score": best_candidate_overlap_score,
            "retry_recommended": retry_recommended and sections_rewritten == 0,
            "run_log": run_log,
        }


async def run_humanizer_pipeline(
    *,
    paper: object,
    formatted_text: str | None = None,
    latex_ready: str | None = None,
    written_draft: object | None = None,
    section_confidences: dict[str, float] | None = None,
    trace_id: str | None = None,
    settings: Settings | None = None,
    config: HumanizerConfig | None = None,
    vertex_client: object | None = None,
    logger_: logging.Logger | None = None,
) -> HumanizerAgentResult:
    """Compatibility async wrapper that returns the legacy structured result."""

    del formatted_text, latex_ready, written_draft, section_confidences, vertex_client

    active_logger = logger_ or logger
    resolved_settings = settings or get_settings()
    resolved_config = config or HumanizerConfig.from_settings(resolved_settings)
    resolved_trace_id = trace_id or str(uuid4())

    if paper in (None, "", {}):
        return _build_error_result(
            code="missing_formatted_paper",
            message="The humanizer agent requires formatter output with a paper snapshot.",
            trace_id=resolved_trace_id,
            details={},
        )

    try:
        parsed_paper = ResearchPaperSchema.model_validate(paper)
    except ValidationError as exc:
        return _build_error_result(
            code="invalid_formatted_paper",
            message="The formatter paper snapshot is malformed and could not be parsed.",
            trace_id=resolved_trace_id,
            details={"validation_errors": exc.errors()},
        )

    section_map = build_section_text_map(parsed_paper)
    runtime = HumanizerRuntimeAgent(config=resolved_config, settings=resolved_settings)
    runtime_result = runtime.run(section_map, iteration=0)
    output = build_humanizer_output(
        paper=parsed_paper,
        runtime_result=runtime_result,
        trace_id=resolved_trace_id,
    )

    active_logger.info(
        "Humanizer pipeline trace %s finished with action=%s composite_after=%.3f mode=%s",
        resolved_trace_id,
        output.graph_action,
        output.ai_pattern_score_after or 0.0,
        runtime_result.get("rewriter_mode", HUMANIZER_MODE),
    )

    return HumanizerAgentResult(
        humanized_draft=HumanizedPaperDraft.model_validate(output.humanized_draft or {}),
        paper_snapshot=GeneratedPaper(
            paper=output.paper,
            formatted_text=output.formatted_text,
            latex_ready=output.latex_ready,
        ),
        trace_id=resolved_trace_id,
        metadata={
            "graph_action": output.graph_action,
            "iteration": output.iteration_count,
            "rewriter_mode": runtime_result.get("rewriter_mode", HUMANIZER_MODE),
            "run_log": runtime_result.get("run_log", []),
        },
    )


def build_humanizer_output(
    *,
    paper: ResearchPaperSchema,
    runtime_result: dict[str, Any],
    trace_id: str | None = None,
) -> "HumanizerAgentOutput":
    """Build the pipeline-facing humanizer output from the raw runtime result."""

    from models.generation import HumanizerAgentOutput

    original_section_map = build_section_text_map(paper)
    updated_sections = {
        key: str(value or "").strip()
        for key, value in dict(runtime_result.get("updated_sections", {})).items()
    }
    generated_paper = build_generated_paper(
        source_paper=paper,
        section_texts=updated_sections,
    )

    section_reports: dict[str, HumanizedSection] = {}
    before_sections = runtime_result.get("scores_before", {}).get("sections", {})
    after_sections = runtime_result.get("scores_after", {}).get("sections", {})
    for section_name in SECTION_ORDER:
        original_text = original_section_map.get(section_name, "").strip()
        final_text = updated_sections.get(section_name, original_text)
        analysis = analyze_section(
            section_name=section_name,
            text=final_text,
        )
        before_scores = before_sections.get(section_name, composite_ai_score(original_text))
        after_scores = after_sections.get(section_name, composite_ai_score(final_text))
        passed_threshold = (
            after_scores.get("composite_score", 0.0) <= MAX_AI_PATTERN_SCORE_TO_PASS
            and after_scores.get("burstiness", 0.0) >= MIN_BURSTINESS_TO_PASS
        )
        needs_writer_loopback = after_scores.get("composite_score", 0.0) > 0.75
        needs_graph_retry = (
            not passed_threshold
            and not needs_writer_loopback
            and runtime_result.get("graph_action") == "retry_humanizer"
        )
        section_reports[section_name] = HumanizedSection(
            section_name=section_name,
            text=final_text,
            diff_summary=build_diff_summary(original_text, final_text),
            report=SectionHumanizationReport(
                section_name=section_name,
                original_text=original_text,
                final_text=final_text,
                original_perplexity=0.0,
                final_perplexity=0.0,
                detected_patterns=analysis.detected_patterns,
                paragraph_reports=[
                    ParagraphHumanizationReport(
                        paragraph_index=index,
                        original_perplexity=0.0,
                        final_perplexity=0.0,
                        cadence_score_before=before_scores.get("cadence_uniformity", 0.0),
                        cadence_score_after=after_scores.get("cadence_uniformity", 0.0),
                        ai_pattern_score_before=before_scores.get("composite_score", 0.0),
                        ai_pattern_score_after=after_scores.get("composite_score", 0.0),
                        rewrites_applied=[],
                    )
                    for index, _ in enumerate(
                        [part for part in final_text.split("\n\n") if part.strip()]
                    )
                ],
                rewrite_iterations=int(runtime_result.get("iteration", 0)),
                passed_threshold=passed_threshold,
                needs_graph_retry=needs_graph_retry,
                needs_writer_loopback=needs_writer_loopback,
            ),
        )

    humanized_draft = HumanizedPaperDraft(
        sections=section_reports,
        global_ai_pattern_score_before=float(
            runtime_result.get("scores_before", {}).get("composite_score", 0.0)
        ),
        global_ai_pattern_score_after=float(
            runtime_result.get("scores_after", {}).get("composite_score", 0.0)
        ),
        global_perplexity_before=float(runtime_result.get("perplexity_before") or 0.0),
        global_perplexity_after=float(runtime_result.get("perplexity_after") or 0.0),
        passed_threshold=runtime_result.get("graph_action") == "accept",
        graph_action=str(runtime_result.get("graph_action", "accept")),
        metadata={
            "iteration_count": int(runtime_result.get("iteration", 0)),
            "sections_skipped": int(runtime_result.get("sections_skipped", 0)),
            "sections_rewritten": int(runtime_result.get("sections_rewritten", 0)),
            "rewriter_mode": runtime_result.get("rewriter_mode", HUMANIZER_MODE),
            "run_log": list(runtime_result.get("run_log", [])),
            "scores_before": runtime_result.get("scores_before", {}),
            "scores_after": runtime_result.get("scores_after", {}),
        },
    )
    return HumanizerAgentOutput(
        paper=generated_paper.paper,
        formatted_text=generated_paper.formatted_text,
        latex_ready=generated_paper.latex_ready,
        humanized_draft=humanized_draft.model_dump(mode="python"),
        ai_pattern_score_before=humanized_draft.global_ai_pattern_score_before,
        ai_pattern_score_after=humanized_draft.global_ai_pattern_score_after,
        perplexity_before=runtime_result.get("perplexity_before"),
        perplexity_after=runtime_result.get("perplexity_after"),
        iteration_count=int(runtime_result.get("iteration", 0)),
        graph_action=humanized_draft.graph_action,
        trace_id=trace_id,
        error=None,
    )


def _build_error_result(
    *,
    code: str,
    message: str,
    trace_id: str,
    details: dict[str, Any],
) -> HumanizerAgentResult:
    return HumanizerAgentResult(
        error=HumanizerAgentError(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details,
        ),
        trace_id=trace_id,
        metadata={"status": "error"},
    )


def _style_persona(section_name: str) -> str:
    personas = {
        "abstract": "Compact and natural academic prose with a crisp opening cadence.",
        "introduction": "Scholarly but human, with more variety in sentence rhythm.",
        "related_work": "Balanced comparative prose that avoids stock survey phrasing.",
        "methodology": "Precise technical writing with less robotic repetition.",
        "results": "Measured, evidence-led prose with stronger cadence variety.",
        "discussion": "Analytical and reflective, closer to an experienced researcher voice.",
        "limitations": "Direct, candid language that still reads naturally.",
        "conclusion": "Concise synthesis with human-sounding emphasis and control.",
    }
    return personas.get(section_name, "Academic but conversational")


def _append_unique(values: list[str], value: str) -> None:
    cleaned = str(value or "").strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)


def _select_graph_action(
    *,
    composite_score: float,
    iteration: int,
    max_iterations: int = MAX_ITERATIONS,
    runtime_budget_exceeded: bool = False,
    sections_rewritten: int | None = None,
) -> str:
    if runtime_budget_exceeded:
        return "accept"
    if sections_rewritten == 0 and iteration > 0:
        return "accept"
    if composite_score > 0.75:
        return "loopback_writing"
    if composite_score > MAX_AI_PATTERN_SCORE_TO_PASS and iteration < max_iterations:
        return "retry_humanizer"
    return "accept"


def _resolve_rewriter_mode(actual_modes: set[str], configured_mode: str) -> str:
    """Resolve the effective rewrite mode used during a humanizer run."""

    normalized = {mode.strip().lower() for mode in actual_modes if str(mode).strip()}
    if not normalized:
        return configured_mode
    if len(normalized) == 1:
        return next(iter(normalized))
    return "mixed"


def _strategy_for_iteration(iteration: int, strategy_order: tuple[str, ...]) -> str:
    strategies = tuple(item.strip() for item in strategy_order if str(item).strip()) or (
        "evidence_section",
        "detector_feedback",
        "overlap_reduction",
    )
    index = min(max(0, int(iteration or 1) - 1), len(strategies) - 1)
    return strategies[index]


def _resolve_strategy(strategies_used: set[str]) -> str | None:
    normalized = {strategy.strip() for strategy in strategies_used if str(strategy).strip()}
    if not normalized:
        return None
    if len(normalized) == 1:
        return next(iter(normalized))
    return "mixed"


if ADKBaseAgent is not None:

    class HumanizerAgent(ADKBaseAgent):
        """Guarded ADK wrapper for the humanizer runtime."""

        settings: Settings = Field(default_factory=get_settings, exclude=True)
        config: HumanizerConfig = Field(default_factory=HumanizerConfig.from_settings, exclude=True)

        def __init__(
            self,
            *,
            settings: Settings | None = None,
            config: HumanizerConfig | None = None,
        ):
            resolved_settings = settings or get_settings()
            resolved_config = config or HumanizerConfig.from_settings(resolved_settings)
            super().__init__(
                name="humanizer_agent",
                description="Humanizes formatted academic manuscript sections using a multi-pass rewrite loop.",
                settings=resolved_settings,
                config=resolved_config,
            )
            self._runtime = HumanizerRuntimeAgent(
                config=resolved_config,
                settings=resolved_settings,
            )

        async def _run_async_impl(self, ctx) -> Any:
            state = ctx.session.state
            trace_id = str(state.get("trace_id") or ctx.invocation_id or uuid4())
            state["trace_id"] = trace_id

            result = await run_humanizer_pipeline(
                paper=state.get("paper"),
                formatted_text=str(state.get("formatted_text") or ""),
                latex_ready=str(state.get("latex_ready") or ""),
                written_draft=state.get("written_draft"),
                section_confidences=state.get("section_confidences"),
                trace_id=trace_id,
                settings=self.settings,
                config=self.config,
            )

            if result.humanized_draft is not None:
                state["humanized_draft"] = result.humanized_draft.model_dump(mode="python")
            if result.paper_snapshot is not None:
                state["humanized_paper_snapshot"] = result.paper_snapshot.model_dump(mode="python")
            if result.error is not None:
                state["humanizer_error"] = result.error.model_dump(mode="python")

            yield Event(
                invocationId=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                turnComplete=True,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=result.model_dump_json(indent=2))],
                ),
            )

else:

    class HumanizerAgent:
        def __init__(self, *args, **kwargs):  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google ADK is unavailable in this environment. "
                f"Import error: {ADK_IMPORT_ERROR}"
            )


runtime = HumanizerRuntimeAgent()
if ADKBaseAgent is not None:  # pragma: no branch
    agent = HumanizerAgent(
        settings=runtime.settings,
        config=runtime.config,
    )

    try:  # pragma: no cover - optional A2A runtime wiring
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("ADK A2A bridge is unavailable: %s", exc)
        to_a2a = None

    if to_a2a is not None:  # pragma: no cover - environment dependent
        try:
            app = to_a2a(agent, public_url=os.environ.get("PUBLIC_URL"))
        except Exception as exc:
            logger.warning("Unable to build A2A app for the humanizer agent: %s", exc)
            app = None
    else:
        app = None
else:
    logger.warning("Google ADK imports are unavailable for the humanizer agent: %s", ADK_IMPORT_ERROR)
    agent = None
    app = None
