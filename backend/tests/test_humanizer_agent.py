from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.humanizer_agent import HumanizerAgent as PipelineHumanizerAgent
from humanizer.agent import HumanizerRuntimeAgent
from humanizer.agent import run_humanizer_pipeline
from humanizer.config import HumanizerConfig
from humanizer.detectors import PassiveVoiceAnalyzer, analyze_section, composite_ai_score
from humanizer.rewriter import (
    CandidateDetectionScore,
    DeterministicRewriter,
    HuggingFaceRewriter,
    HybridSectionRewriter,
    HumanizerRewriter,
    NoChangeRewriter,
    RewriteAttemptResult,
    VertexRewriter,
)
from humanizer.perplexity import PerplexityScorer
from models.a2a import A2AMessage
from models.agent_runtime import AgentSpec
from models.generation import FormattingAgentOutput, HumanizerAgentOutput, IEEESectionMap, ResearchPaperSchema
from core.vertex_client import VertexGeminiClient


def _run(coro):
    return asyncio.run(coro)


def _build_paper() -> ResearchPaperSchema:
    return ResearchPaperSchema(
        title="Evidence-Grounded IEEE Workflow",
        abstract=(
            "Furthermore, this workflow improves academic drafting by 95% in internal review [1]. "
            "Furthermore, it is important to note that the system may preserve provenance with \\cite{trace}."
        ),
        keywords=["IEEE drafting", "provenance", "workflow"],
        sections=IEEESectionMap(
            introduction=(
                "Furthermore, the workflow supports evidence tracking. Furthermore, the workflow supports author review."
            ),
            related_work=(
                "Moreover, prior systems emphasize fluency. Moreover, prior systems often omit provenance."
            ),
            methodology=(
                "The system was evaluated on the benchmark dataset. The dataset was processed by the pipeline. "
                "The benchmark was configured with the default protocol."
            ),
            results=(
                "Furthermore, the model improved accuracy by 12% on PubMedBERT [1]. "
                "Furthermore, the model retained 95% citation fidelity with \\cite{pubmedbert}."
            ),
            discussion=(
                "Additionally, the results suggest the workflow may improve adoption. "
                "Additionally, the discussion suggests the workflow may improve trust."
            ),
            limitations=(
                "The study is limited to one dataset. The evidence remains limited for weak source documents."
            ),
            conclusion=(
                "Overall, the workflow supports IEEE manuscript preparation. Overall, the workflow preserves evidence."
            ),
        ),
        references=[
            "[1] A. Author, \"Traceable Academic Drafting,\" IEEE Access, 2025.",
        ],
    )


class FakeVertexClient:
    async def generate_json(self, *, prompt, response_schema, model_name=None):
        return response_schema(
            rewritten_text=(
                "The workflow improves academic drafting by 95% in internal review [1], "
                "while it may preserve provenance with \\cite{trace}."
            ),
            rewrite_notes=["Applied concise cadence variation."],
        )


def test_missing_formatted_paper_returns_structured_error():
    result = _run(
        run_humanizer_pipeline(
            paper=None,
            config=HumanizerConfig(use_model_rewriter=False, enable_perplexity=False),
        )
    )

    assert result.error is not None
    assert result.error.code == "missing_formatted_paper"
    assert result.humanized_draft is None


def test_valid_formatted_paper_produces_humanized_outputs():
    paper = _build_paper()
    result = _run(
        run_humanizer_pipeline(
            paper=paper,
            formatted_text="formatted",
            latex_ready="latex",
            config=HumanizerConfig(use_model_rewriter=False, enable_perplexity=False, max_iterations=2),
            vertex_client=FakeVertexClient(),
            section_confidences={"limitations": 0.35},
        )
    )

    assert result.error is None
    assert result.humanized_draft is not None
    assert result.paper_snapshot is not None
    assert result.paper_snapshot.formatted_text
    assert result.paper_snapshot.latex_ready
    assert result.humanized_draft.graph_action in {"accept", "retry_humanizer", "loopback_writing"}
    for section_name in (
        "abstract",
        "introduction",
        "related_work",
        "methodology",
        "results",
        "discussion",
        "limitations",
        "conclusion",
    ):
        assert section_name in result.humanized_draft.sections


def test_protected_spans_remain_unchanged_after_rewrite():
    paper = _build_paper()
    result = _run(
        run_humanizer_pipeline(
            paper=paper,
            formatted_text="formatted",
            latex_ready="latex",
            config=HumanizerConfig(use_model_rewriter=False, enable_perplexity=False),
        )
    )

    assert result.paper_snapshot is not None
    results_text = result.paper_snapshot.paper.sections.results
    assert "12%" in results_text
    assert "95%" in results_text
    assert "[1]" in results_text
    assert "\\cite{pubmedbert}" in results_text


def test_detector_flags_uniform_cadence_and_repetition(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(PassiveVoiceAnalyzer, "score_text", lambda self, text: (0.6, ["The model was evaluated on the benchmark dataset."]))
    analysis = analyze_section(
        section_name="methodology",
        text=(
            "Furthermore, the model was evaluated on the benchmark dataset. "
            "Furthermore, the model was trained on the benchmark dataset. "
            "Furthermore, the model was tested on the benchmark dataset."
        ),
        config=HumanizerConfig(enable_perplexity=False),
    )

    pattern_types = {pattern.pattern_type for pattern in analysis.detected_patterns}
    assert "uniform_sentence_cadence" in pattern_types or "repetitive_transitions" in pattern_types
    assert "passive_voice_overuse" in pattern_types


def test_detector_flags_stock_ai_phrases_and_em_dash_patterns():
    analysis = analyze_section(
        section_name="discussion",
        text=(
            "Of course, the workflow has the ability to scale — no guessing — during review. "
            "In order to achieve this goal, it serves as a reliable foundation."
        ),
        config=HumanizerConfig(enable_perplexity=False),
    )

    pattern_types = {pattern.pattern_type for pattern in analysis.detected_patterns}
    assert "stock_ai_phrases" in pattern_types
    assert "em_dash_overuse" in pattern_types


def test_rewrite_loop_improves_style_score(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        HuggingFaceRewriter,
        "rewrite_paragraph",
        lambda self, **kwargs: RewriteAttemptResult(
            text="The discussion points to stronger trust in the workflow, while adoption also appears more plausible.",
            rewriter_used="huggingface",
            changed=True,
        ),
    )
    config = HumanizerConfig(
        rewriter_backend="huggingface",
        use_model_rewriter=True,
        enable_perplexity=False,
        max_iterations=2,
    )
    rewriter = HybridSectionRewriter(
        config=config,
        vertex_client=None,
        perplexity_scorer=PerplexityScorer(config),
    )

    outcome = _run(
        rewriter.humanize_section(
            section_name="discussion",
            text=(
                "Additionally, the discussion suggests the workflow may improve trust. "
                "Additionally, the discussion suggests the workflow may improve adoption."
            ),
            section_confidence=0.58,
            trace_id="trace-humanizer",
        )
    )

    assert outcome.applied_changes
    assert outcome.analysis_after.ai_pattern_score <= outcome.analysis_before.ai_pattern_score


def test_backend_selection_prefers_huggingface():
    rewriter = HumanizerRewriter(HumanizerConfig(rewriter_backend="huggingface"))
    assert isinstance(rewriter.backend, HuggingFaceRewriter)


def test_backend_selection_supports_none():
    rewriter = HumanizerRewriter(HumanizerConfig(rewriter_backend="none"))
    assert isinstance(rewriter.backend, NoChangeRewriter)


def test_hf_failure_returns_unchanged_and_never_calls_deterministic(monkeypatch: pytest.MonkeyPatch):
    def fail_hf(self, **kwargs):
        return RewriteAttemptResult(
            text=kwargs["target_para"],
            rewriter_used="none",
            changed=False,
            failure_reason="model_load_failed",
        )

    def fail_deterministic(self, text):
        raise AssertionError("Deterministic fallback must not be used")

    monkeypatch.setattr(HuggingFaceRewriter, "rewrite_paragraph", fail_hf)
    monkeypatch.setattr(DeterministicRewriter, "apply_all", fail_deterministic)

    rewriter = HumanizerRewriter(HumanizerConfig(rewriter_backend="huggingface"))
    original = (
        "Furthermore, the model improved accuracy by 12% on PubMedBERT [1]. "
        "Furthermore, the model retained 95% citation fidelity with \\cite{pubmedbert}."
    )
    result = rewriter.rewrite_section(original, composite_ai_score(original), section_name="results")

    assert result["rewritten_text"] == original
    assert result["changed"] is False
    assert result["rewriter_used"] == "none"
    assert "model_load_failed" in result["failure_reasons"]


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            "The workflow improved accuracy by 12% on PubMedBERT and retained citation fidelity.",
            "protected_span_changed",
        ),
        (
            "The workflow improved accuracy by 18% on PubMedBERT [1] and retained 95% citation fidelity with \\cite{pubmedbert}.",
            "protected_span_changed",
        ),
    ],
)
def test_hf_rejected_output_returns_unchanged(monkeypatch: pytest.MonkeyPatch, candidate: str, reason: str):
    monkeypatch.setattr(
        HuggingFaceRewriter,
        "rewrite_paragraph",
        lambda self, **kwargs: RewriteAttemptResult(
            text=candidate,
            rewriter_used="huggingface",
            changed=True,
        ),
    )
    monkeypatch.setattr(
        DeterministicRewriter,
        "apply_all",
        lambda self, text: (_ for _ in ()).throw(AssertionError("Deterministic fallback must not run")),
    )

    rewriter = HumanizerRewriter(HumanizerConfig(rewriter_backend="huggingface"))
    original = (
        "Furthermore, the model improved accuracy by 12% on PubMedBERT [1]. "
        "Furthermore, the model retained 95% citation fidelity with \\cite{pubmedbert}."
    )
    result = rewriter.rewrite_section(original, composite_ai_score(original), section_name="results")

    assert result["rewritten_text"] == original
    assert result["changed"] is False
    assert result["rewriter_used"] == "none"
    assert reason in result["failure_reasons"]


def test_hf_semantic_drift_failure_returns_unchanged(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        HuggingFaceRewriter,
        "rewrite_paragraph",
        lambda self, **kwargs: RewriteAttemptResult(
            text="Climate change is accelerating due to greenhouse gas emissions.",
            rewriter_used="huggingface",
            changed=True,
        ),
    )

    rewriter = HumanizerRewriter(
        HumanizerConfig(rewriter_backend="huggingface", semantic_drift_threshold=0.0),
    )
    original = "Furthermore, the model improved accuracy by 12% on the benchmark dataset [1]."
    result = rewriter.rewrite_section(original, composite_ai_score(original), section_name="results")

    assert result["rewritten_text"] == original
    assert result["changed"] is False
    assert result["rewriter_used"] == "none"
    assert "semantic_drift" in result["failure_reasons"]


def test_valid_hf_output_is_accepted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "humanizer.rewriter.verify_rewrite_safety",
        lambda **kwargs: type("SafetyResult", (), {"passed": True, "reasons": []})(),
    )
    monkeypatch.setattr(
        HuggingFaceRewriter,
        "rewrite_paragraph",
        lambda self, **kwargs: RewriteAttemptResult(
            text=(
                "The model improved accuracy by 12% on PubMedBERT [1], while preserving 95% "
                "citation fidelity with \\cite{pubmedbert} across evaluation."
            ),
            rewriter_used="huggingface",
            changed=True,
        ),
    )

    rewriter = HumanizerRewriter(HumanizerConfig(rewriter_backend="huggingface"))
    original = (
        "Furthermore, the model improved accuracy by 12% on PubMedBERT [1]. "
        "Furthermore, the model retained 95% citation fidelity with \\cite{pubmedbert}."
    )
    result = rewriter.rewrite_section(original, composite_ai_score(original), section_name="results")

    assert result["rewriter_used"] == "huggingface"
    assert result["changed"] is True
    assert result["rewritten_text"] != original


def test_targeted_runtime_forces_rewrite_even_when_local_score_passes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "humanizer.agent.composite_ai_score",
        lambda text: {
            "composite_score": 0.1,
            "burstiness": 0.8,
            "transition_uniformity": 0.1,
            "cadence_uniformity": 0.1,
        },
    )
    captured: dict[str, object] = {}

    def fake_rewrite_section(
        self,
        section_text,
        ai_scores,
        style_persona="Academic but conversational",
        *,
        section_name=None,
        force_rewrite=False,
        require_quality_improvement=True,
    ):
        del self, ai_scores, style_persona
        captured["section_name"] = section_name
        captured["force_rewrite"] = force_rewrite
        captured["require_quality_improvement"] = require_quality_improvement
        return {
            "rewritten_text": f"{section_text} Revised.",
            "paragraphs_targeted": 1,
            "paragraphs_accepted": 1,
            "paragraphs_rejected_drift": 0,
            "rewriter_used": "vertex",
            "changed": True,
            "failure_reasons": [],
        }

    monkeypatch.setattr(HumanizerRewriter, "rewrite_section", fake_rewrite_section)

    runtime = HumanizerRuntimeAgent(
        config=HumanizerConfig(rewriter_backend="none", enable_perplexity=False),
    )
    result = runtime.run(
        {
            "introduction": (
                "This section reads as locally acceptable, but Desklib still flagged it for review."
            )
        },
        iteration=1,
        target_sections={"introduction"},
    )

    assert captured == {
        "section_name": "introduction",
        "force_rewrite": True,
        "require_quality_improvement": False,
    }
    assert result["sections_rewritten"] == 1
    assert result["rewriter_mode"] == "vertex"


def test_forced_rewrite_accepts_safe_candidate_without_local_quality_gain(
    monkeypatch: pytest.MonkeyPatch,
):
    score = {
        "composite_score": 0.1,
        "burstiness": 0.8,
        "transition_uniformity": 0.1,
        "cadence_uniformity": 0.1,
    }
    monkeypatch.setattr("humanizer.rewriter.composite_ai_score", lambda text: dict(score))
    monkeypatch.setattr(
        "humanizer.rewriter.verify_rewrite_safety",
        lambda **kwargs: type("SafetyResult", (), {"passed": True, "reasons": []})(),
    )
    monkeypatch.setattr(
        "humanizer.rewriter.SemanticDriftChecker.drift",
        lambda self, original, rewritten: 0.0,
    )
    monkeypatch.setattr(
        HuggingFaceRewriter,
        "rewrite_paragraph",
        lambda self, **kwargs: RewriteAttemptResult(
            text=(
                "This study compares two training settings, reports a 12% improvement [1], "
                "and preserves \\cite{trace} across review."
            ),
            rewriter_used="huggingface",
            changed=True,
        ),
    )

    rewriter = HumanizerRewriter(HumanizerConfig(rewriter_backend="huggingface"))
    original = (
        "The study compares two training settings with 12% improvement [1] and preserves "
        "\\cite{trace} across review."
    )
    result = rewriter.rewrite_section(
        original,
        composite_ai_score(original),
        section_name="results",
        force_rewrite=True,
        require_quality_improvement=False,
    )

    assert result["paragraphs_targeted"] == 1
    assert result["rewriter_used"] == "huggingface"
    assert result["changed"] is True
    assert result["rewritten_text"] != original


def test_vertex_candidate_generation_parses_multiple_options():
    class FakeModels:
        def generate_content(self, *, model, contents):
            assert model == "gemini-test"
            assert "strict JSON array" in contents
            return type(
                "Response",
                (),
                {
                    "text": (
                        "["
                        "\"The study reports a 12% improvement [1] while preserving \\\\cite{trace}.\", "
                        "\"Across the study, the 12% improvement [1] remains linked to \\\\cite{trace}.\""
                        "]"
                    )
                },
            )()

    rewriter = VertexRewriter.__new__(VertexRewriter)
    rewriter.available = True
    rewriter._client = type("Client", (), {"models": FakeModels()})()
    rewriter.model = "gemini-test"
    rewriter.timeout_seconds = 5

    results = rewriter.rewrite_paragraph_candidates(
        target_para="The study reports a 12% improvement [1] with \\cite{trace}.",
        section_context="The study reports a 12% improvement [1] with \\cite{trace}.",
        style_persona="Academic but natural",
        ai_scores={"burstiness": 0.3, "cadence_uniformity": 0.8, "transition_uniformity": 0.4},
        candidate_count=2,
        rewrite_mode="academic-natural",
    )

    assert len(results) == 2
    assert all(result.changed for result in results)
    assert all(result.rewriter_used == "vertex" for result in results)


def test_multi_candidate_rewrite_selects_safe_lowest_score_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    class CandidateBackend:
        def rewrite_paragraph_candidates(self, **kwargs):
            return [
                RewriteAttemptResult(
                    text="A different climate paragraph with 12% improvement [1] and \\cite{trace}.",
                    rewriter_used="vertex",
                    changed=True,
                ),
                RewriteAttemptResult(
                    text=(
                        "The study reports a 12% improvement [1], while preserving \\cite{trace} "
                        "throughout the review."
                    ),
                    rewriter_used="vertex",
                    changed=True,
                ),
            ]

    def fake_score(text):
        if "throughout the review" in text:
            return {
                "composite_score": 0.2,
                "burstiness": 0.7,
                "transition_uniformity": 0.1,
                "cadence_uniformity": 0.1,
            }
        return {
            "composite_score": 0.6,
            "burstiness": 0.3,
            "transition_uniformity": 0.5,
            "cadence_uniformity": 0.5,
        }

    monkeypatch.setattr("humanizer.rewriter.composite_ai_score", fake_score)
    monkeypatch.setattr(
        "humanizer.rewriter.verify_rewrite_safety",
        lambda **kwargs: type("SafetyResult", (), {"passed": True, "reasons": [], "similarity": 0.9})(),
    )
    monkeypatch.setattr(
        "humanizer.rewriter.SemanticDriftChecker.drift",
        lambda self, original, rewritten: 0.8 if "climate" in rewritten else 0.0,
    )

    rewriter = HumanizerRewriter(
        HumanizerConfig(rewriter_backend="none", rewrite_candidate_count=2),
    )
    rewriter.backend = CandidateBackend()
    original = "The study reports a 12% improvement [1] with \\cite{trace}."
    result = rewriter.rewrite_section(
        original,
        composite_ai_score(original),
        section_name="results",
        force_rewrite=True,
        require_quality_improvement=False,
    )

    assert result["changed"] is True
    assert result["rewriter_used"] == "vertex"
    assert "throughout the review" in result["rewritten_text"]
    assert "semantic_drift" in result["failure_reasons"]


def test_desklib_candidate_scoring_ranks_candidates_ahead_of_local_score(
    monkeypatch: pytest.MonkeyPatch,
):
    class CandidateBackend:
        def rewrite_paragraph_candidates(self, **kwargs):
            return [
                RewriteAttemptResult(
                    text="The study reports a 12% improvement [1], and \\cite{trace} documents the review.",
                    rewriter_used="vertex",
                    changed=True,
                ),
                RewriteAttemptResult(
                    text=(
                        "The 12% improvement [1] appears in the review record, with \\cite{trace} "
                        "kept as supporting evidence."
                    ),
                    rewriter_used="vertex",
                    changed=True,
                ),
            ]

    class FakeDesklibScorer:
        def score_text(self, text):
            if "appears in the review record" in text:
                return CandidateDetectionScore(score=0.21, backend="desklib")
            if "documents the review" in text:
                return CandidateDetectionScore(score=0.84, backend="desklib")
            return CandidateDetectionScore(score=0.95, backend="desklib")

    def fake_local_score(text):
        if "documents the review" in text:
            return {
                "composite_score": 0.1,
                "burstiness": 0.8,
                "transition_uniformity": 0.1,
                "cadence_uniformity": 0.1,
            }
        return {
            "composite_score": 0.5,
            "burstiness": 0.4,
            "transition_uniformity": 0.4,
            "cadence_uniformity": 0.4,
        }

    monkeypatch.setattr("humanizer.rewriter.composite_ai_score", fake_local_score)
    monkeypatch.setattr(
        "humanizer.rewriter.verify_rewrite_safety",
        lambda **kwargs: type("SafetyResult", (), {"passed": True, "reasons": [], "similarity": 0.9})(),
    )
    monkeypatch.setattr(
        "humanizer.rewriter.SemanticDriftChecker.drift",
        lambda self, original, rewritten: 0.0,
    )
    monkeypatch.setattr(
        HumanizerRewriter,
        "_build_detector_scorer",
        lambda self: FakeDesklibScorer(),
    )

    rewriter = HumanizerRewriter(
        HumanizerConfig(
            rewriter_backend="none",
            use_desklib_candidate_scoring=True,
            rewrite_candidate_count=2,
        ),
    )
    rewriter.backend = CandidateBackend()
    original = "The study reports a 12% improvement [1] with \\cite{trace}."
    result = rewriter.rewrite_section(
        original,
        composite_ai_score(original),
        section_name="results",
        force_rewrite=True,
        require_quality_improvement=False,
    )

    assert result["changed"] is True
    assert result["rewriter_used"] == "vertex"
    assert "appears in the review record" in result["rewritten_text"]


def test_desklib_candidate_scoring_rejects_non_improving_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    class CandidateBackend:
        def rewrite_paragraph_candidates(self, **kwargs):
            return [
                RewriteAttemptResult(
                    text=(
                        "The study reports a 12% improvement [1], while \\cite{trace} remains "
                        "available for review."
                    ),
                    rewriter_used="vertex",
                    changed=True,
                )
            ]

    class FakeDesklibScorer:
        def score_text(self, text):
            if "available for review" in text:
                return CandidateDetectionScore(score=0.96, backend="desklib")
            return CandidateDetectionScore(score=0.95, backend="desklib")

    monkeypatch.setattr(
        "humanizer.rewriter.verify_rewrite_safety",
        lambda **kwargs: type("SafetyResult", (), {"passed": True, "reasons": [], "similarity": 0.9})(),
    )
    monkeypatch.setattr(
        "humanizer.rewriter.SemanticDriftChecker.drift",
        lambda self, original, rewritten: 0.0,
    )
    monkeypatch.setattr(
        HumanizerRewriter,
        "_build_detector_scorer",
        lambda self: FakeDesklibScorer(),
    )

    rewriter = HumanizerRewriter(
        HumanizerConfig(rewriter_backend="none", use_desklib_candidate_scoring=True),
    )
    rewriter.backend = CandidateBackend()
    original = "The study reports a 12% improvement [1] with \\cite{trace}."
    result = rewriter.rewrite_section(
        original,
        composite_ai_score(original),
        section_name="results",
        force_rewrite=True,
        require_quality_improvement=False,
    )

    assert result["changed"] is False
    assert result["rewritten_text"] == original
    assert "desklib_not_improved" in result["failure_reasons"]


def test_desklib_candidate_scorer_failure_returns_no_change(
    monkeypatch: pytest.MonkeyPatch,
):
    class FailingDesklibScorer:
        def score_text(self, text):
            return CandidateDetectionScore(
                score=None,
                backend="desklib",
                failure_reason="desklib_scorer_unavailable",
            )

    monkeypatch.setattr(
        HumanizerRewriter,
        "_build_detector_scorer",
        lambda self: FailingDesklibScorer(),
    )

    rewriter = HumanizerRewriter(
        HumanizerConfig(rewriter_backend="none", use_desklib_candidate_scoring=True),
    )
    original = "The study reports a 12% improvement [1] with \\cite{trace}."
    result = rewriter.rewrite_section(
        original,
        composite_ai_score(original),
        section_name="results",
        force_rewrite=True,
        require_quality_improvement=False,
    )

    assert result["changed"] is False
    assert result["rewritten_text"] == original
    assert "desklib_scorer_unavailable" in result["failure_reasons"]


def test_fallback_semantic_threshold_accepts_safe_candidate_when_embedding_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        HuggingFaceRewriter,
        "rewrite_paragraph",
        lambda self, **kwargs: RewriteAttemptResult(
            text=(
                "The study reports a 12% improvement [1], and \\cite{trace} remains "
                "part of the review evidence."
            ),
            rewriter_used="huggingface",
            changed=True,
        ),
    )
    monkeypatch.setattr(
        "humanizer.rewriter.verify_rewrite_safety",
        lambda **kwargs: type("SafetyResult", (), {"passed": True, "reasons": [], "similarity": 0.72})(),
    )
    monkeypatch.setattr(
        "humanizer.rewriter.SemanticDriftChecker.drift",
        lambda self, original, rewritten: 0.25,
    )

    rewriter = HumanizerRewriter(
        HumanizerConfig(rewriter_backend="huggingface", semantic_drift_threshold=0.15),
    )
    rewriter.semantic_drift.available = False
    original = "The study reports a 12% improvement [1] with \\cite{trace}."
    result = rewriter.rewrite_section(
        original,
        composite_ai_score(original),
        section_name="results",
        force_rewrite=True,
        require_quality_improvement=False,
    )

    assert result["changed"] is True
    assert result["rewriter_used"] == "huggingface"
    assert "semantic_drift" not in result["failure_reasons"]


def test_limitations_are_not_softened():
    paper = _build_paper()
    result = _run(
        run_humanizer_pipeline(
            paper=paper,
            formatted_text="formatted",
            latex_ready="latex",
            config=HumanizerConfig(use_model_rewriter=False, enable_perplexity=False),
            section_confidences={"limitations": 0.32},
        )
    )

    assert result.humanized_draft is not None
    limitations = result.humanized_draft.sections["limitations"].text.lower()
    assert "limit" in limitations


def test_compatibility_wrapper_returns_legacy_payload(monkeypatch: pytest.MonkeyPatch):
    pipeline_result = _run(
        run_humanizer_pipeline(
            paper=_build_paper(),
            formatted_text="formatted",
            latex_ready="latex",
            config=HumanizerConfig(use_model_rewriter=False, enable_perplexity=False),
        )
    )

    async def fake_run_humanizer_pipeline(**kwargs):
        return pipeline_result

    monkeypatch.setattr("agents.humanizer_agent.run_humanizer_pipeline", fake_run_humanizer_pipeline)

    spec = AgentSpec(
        name="humanizer_agent",
        role="test",
        input_schema="FormattingAgentOutput",
        output_schema="HumanizerAgentOutput",
        model="gemini-2.5-flash",
    )
    agent = PipelineHumanizerAgent(client=VertexGeminiClient(), spec=spec)
    formatting_output = FormattingAgentOutput(
        paper=_build_paper(),
        formatted_text="formatted",
        latex_ready="latex",
    )
    message = A2AMessage(
        sender="ieee_formatting_agent",
        recipient="humanizer_agent",
        task="humanize_ieee_paper",
        trace_id="trace-humanizer",
        payload={"paper": formatting_output.model_dump(mode="python")},
    )

    payload = _run(agent.process_task(message))
    output = HumanizerAgentOutput.model_validate(payload)

    assert output.humanized_draft is not None
    assert output.formatted_text
    assert output.latex_ready
