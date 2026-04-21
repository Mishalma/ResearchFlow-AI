from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from humanizer.detectors import (
    burstiness_score,
    composite_ai_score,
    em_dash_overuse_score,
    stock_phrase_density_score,
    transition_uniformity_score,
)
from humanizer.rewriter import DeterministicRewriter
from humanizer.semantic_drift import SemanticDriftChecker
from humanizer.utils import semantic_similarity, verify_rewrite_safety
from models.generation import HumanizerAgentOutput, IEEESectionMap, ResearchPaperSchema
from orchestration.pipeline import _execute_humanizer_loop


def test_burstiness_low_on_ai_text():
    ai_text = (
        "The model performs well. It achieves high accuracy. The results are significant. "
        "Performance is consistent. The approach is effective. Results confirm this."
    )
    assert burstiness_score(ai_text) < 0.4


def test_burstiness_high_on_human_text():
    human_text = (
        "What strikes you immediately is the sheer scale. Over three million data "
        "points, collected across fourteen countries, spanning nearly a decade of "
        "continuous monitoring - and yet the signal is unmistakable. It holds."
    )
    assert burstiness_score(human_text) > 0.5


def test_transition_detection():
    text = "Furthermore, the model is good. Moreover, it scales well. In addition, it is fast."
    score = transition_uniformity_score(text)
    assert score > 0.5


def test_semantic_drift_safe():
    checker = SemanticDriftChecker()
    if checker.available:
        original = "The model achieves high accuracy on the benchmark dataset."
        rewrite = "The proposed approach performs strongly across standard evaluations."
        assert checker.is_safe(original, rewrite)


def test_semantic_drift_unsafe():
    checker = SemanticDriftChecker()
    if checker.available:
        original = "The model achieves high accuracy on the benchmark dataset."
        drift_text = "Climate change is accelerating due to greenhouse gas emissions."
        assert not checker.is_safe(original, drift_text)


def test_semantic_similarity_handles_academic_paraphrase():
    original = "The model achieves high accuracy on the benchmark dataset."
    rewrite = "The proposed approach performs strongly across standard evaluations."
    assert semantic_similarity(original, rewrite) >= 0.65


def test_rewrite_safety_rejects_changed_numbers():
    safety = verify_rewrite_safety(
        original="The workflow improved accuracy by 12% on the benchmark dataset [1].",
        rewritten="The workflow improved accuracy by 18% on the benchmark dataset [1].",
        similarity_threshold=0.6,
    )
    assert not safety.passed
    assert "number_tokens_changed" in safety.reasons


def test_deterministic_rewriter_removes_transitions():
    rewriter = DeterministicRewriter()
    text = "Furthermore, the results are clear. Moreover, this confirms our hypothesis."
    out = rewriter.apply_all(text)
    assert "Furthermore" not in out
    assert "Moreover" not in out


def test_deterministic_rewriter_applies_anti_ai_cleanup():
    rewriter = DeterministicRewriter()
    text = (
        "Of course, the system has the ability to process each request — no guessing. "
        "In order to achieve this goal, it serves as a reliable workflow."
    )
    out = rewriter.apply_all(text)
    assert "Of course" not in out
    assert "has the ability to" not in out
    assert "In order to" not in out
    assert "serves as" not in out
    assert "—" not in out
    assert "no guessing" not in out


def test_stock_phrase_density_flags_formulaic_ai_copy():
    text = (
        "Of course, the system has the ability to process requests. "
        "In order to achieve this goal, it uses a structured workflow."
    )
    assert stock_phrase_density_score(text) > 0.5


def test_em_dash_overuse_score_flags_multiple_dashes():
    text = (
        "The system works — in practice — because the workflow is stable. "
        "It adapts — even under stress."
    )
    assert em_dash_overuse_score(text) > 0.5


def test_pipeline_loop_calls_retry():
    class FakeHumanizerAgent:
        def __init__(self):
            self.calls = 0

        def run(self, section_map, *, paper, iteration=0):
            self.calls += 1
            action = "accept" if self.calls == 3 else "retry_humanizer"
            return {
                "updated_sections": section_map,
                "graph_action": action,
                "scores_before": {"composite_score": 0.8},
                "scores_after": {"composite_score": 0.7 if action != "accept" else 0.4},
                "perplexity_before": None,
                "perplexity_after": None,
                "iteration": iteration,
                "sections_skipped": 0,
                "sections_rewritten": 1,
                "rewriter_mode": "deterministic",
                "run_log": [],
            }

        def build_output(self, *, paper, runtime_result, trace_id=None):
            return HumanizerAgentOutput(
                paper=paper,
                formatted_text="formatted",
                latex_ready="latex",
                humanized_draft={"graph_action": runtime_result["graph_action"]},
                ai_pattern_score_before=runtime_result["scores_before"]["composite_score"],
                ai_pattern_score_after=runtime_result["scores_after"]["composite_score"],
                graph_action=runtime_result["graph_action"],
                iteration_count=runtime_result["iteration"],
                trace_id=trace_id,
            )

    fake_agent = FakeHumanizerAgent()
    paper = ResearchPaperSchema(
        title="Test Paper",
        abstract="Abstract text.",
        keywords=["test"],
        sections=IEEESectionMap(
            introduction="Intro text.",
            related_work="Related work.",
            methodology="Methodology text.",
            results="Results text.",
            discussion="Discussion text.",
            limitations="Limitations text.",
            conclusion="Conclusion text.",
        ),
        references=["[1] Ref."],
    )
    result = _execute_humanizer_loop(
        humanizer_agent=fake_agent,
        paper=paper,
        trace_id="trace-humanizer",
        pipeline_context={},
    )
    assert fake_agent.calls == 3
    assert result.graph_action == "accept"


def test_composite_score_structure():
    result = composite_ai_score("Some text here.")
    for key in [
        "burstiness",
        "lexical_repetition",
        "transition_uniformity",
        "cadence_uniformity",
        "passive_voice_ratio",
        "stock_phrase_density",
        "em_dash_overuse",
        "composite_score",
    ]:
        assert key in result
