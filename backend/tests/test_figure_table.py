from __future__ import annotations

import asyncio
import base64
from dataclasses import replace

from app.models.project import ProjectRecord
from app.services import project_service
from core.config import get_settings
from figure_table.extractor import FigureExtractor
from figure_table.generator import FigureGenerator
from figure_table.injector import ManuscriptInjector
from figure_table.models import FigureSpec, FigureTableOutput, FigureType, RenderedFigure
from figure_table.runtime import FigureTableRuntime
from formatting.utils import normalize_paragraphs_for_latex
from models.generation import FigureTableAgentOutput, IEEESectionMap, WritingAgentOutput
from orchestration.pipeline import _dispatch_figure_table_stage, _merge_writing_with_figures


class _FakeGeminiClient:
    def __init__(self, payload):
        self.payload = payload

    async def generate_json(self, *, prompt, response_schema):
        del prompt
        return response_schema.model_validate(self.payload)


def _written_draft_payload() -> dict:
    return {
        "title": "Visual Manuscript",
        "abstract": {
            "section_name": "abstract",
            "text": "This paper reports model performance improvements.",
            "confidence": 0.8,
        },
        "sections": {
            "introduction": {"section_name": "introduction", "text": "Introduction text.", "confidence": 0.7},
            "related_work": {"section_name": "related_work", "text": "Related work text.", "confidence": 0.7},
            "methodology": {"section_name": "methodology", "text": "Methodology text.", "confidence": 0.7},
            "results": {
                "section_name": "results",
                "text": "The system achieved 95% accuracy on the benchmark dataset.",
                "confidence": 0.9,
            },
            "discussion": {"section_name": "discussion", "text": "Discussion text.", "confidence": 0.7},
            "limitations": {"section_name": "limitations", "text": "Limitations text.", "confidence": 0.5},
            "conclusion": {"section_name": "conclusion", "text": "Conclusion text.", "confidence": 0.7},
        },
        "global_confidence": 0.75,
        "metadata": {"keywords": ["IEEE", "visualization"], "references": ["[1] Example."]},
    }


def test_extractor_parses_valid_payload():
    extractor = FigureExtractor()
    specs = asyncio.run(
        extractor.extract(
            "Sample draft",
            _FakeGeminiClient(
                {
                    "figures": [
                        {
                            "id": "figX",
                            "type": "bar_chart",
                            "section": "results",
                            "title": "Performance comparison",
                            "caption": "Comparison of performance",
                            "is_table": False,
                            "placement_hint": "The system achieved 95% accuracy on the benchmark dataset.",
                            "data": {
                                "x_label": "Method",
                                "y_label": "Accuracy",
                                "x_values": ["A", "B"],
                                "series": [{"name": "Score", "values": [91, 95], "color": "#2196F3"}],
                            },
                        },
                        {
                            "id": "tabX",
                            "type": "table",
                            "section": "results",
                            "title": "Results table",
                            "caption": "Summary values",
                            "is_table": True,
                            "placement_hint": "The system achieved 95% accuracy on the benchmark dataset.",
                            "data": {"headers": ["Metric", "Value"], "rows": [["Accuracy", "95"]]},
                        },
                    ]
                }
            ),
        )
    )

    assert len(specs) == 2
    assert specs[0].id == "fig1"
    assert specs[0].figure_number == 1
    assert specs[1].id == "tab1"
    assert specs[1].table_number == 1


def test_extractor_returns_empty_list_on_failure():
    extractor = FigureExtractor()

    class _FailingClient:
        async def generate_json(self, *, prompt, response_schema):
            del prompt, response_schema
            raise RuntimeError("boom")

    specs = asyncio.run(extractor.extract("Sample draft", _FailingClient()))
    assert specs == []


def test_table_renderer_returns_valid_rendered_figure():
    generator = FigureGenerator()
    spec = FigureSpec(
        id="tab1",
        type=FigureType.TABLE,
        section="results",
        title="Results table",
        caption="Table I. Benchmark summary.",
        data={"headers": ["Metric", "Value"], "rows": [["Accuracy", "95"], ["F1", "93"]]},
        placement_hint="The system achieved 95% accuracy on the benchmark dataset.",
        is_table=True,
        table_number=1,
    )
    rendered = asyncio.run(generator.render_one(spec))
    assert rendered.render_success
    assert rendered.latex_table is not None
    assert "\\begin{table}" in rendered.latex_block


def test_table_renderer_handles_scalar_rows():
    generator = FigureGenerator()
    spec = FigureSpec(
        id="tab1",
        type=FigureType.TABLE,
        section="results",
        title="Results table",
        caption="Table I. Scalar summary.",
        data={"headers": ["Metric", "Value"], "rows": [95, 93]},
        placement_hint="The system achieved 95% accuracy on the benchmark dataset.",
        is_table=True,
        table_number=1,
    )
    rendered = asyncio.run(generator.render_one(spec))
    assert rendered.render_success
    assert "95 &" in rendered.latex_block or "95" in rendered.latex_block


def test_injector_is_idempotent():
    injector = ManuscriptInjector()
    text = (
        "Abstract\nAbstract text.\n\n"
        "Index Terms - IEEE, visualization\n\n"
        "IV. RESULTS\n"
        "The system achieved 95% accuracy on the benchmark dataset.\n\n"
        "References\n[1] Example."
    )
    spec = FigureSpec(
        id="fig1",
        type=FigureType.BAR_CHART,
        section="results",
        title="Accuracy chart",
        caption="Fig. 1. Accuracy comparison.",
        data={},
        placement_hint="The system achieved 95% accuracy on the benchmark dataset.",
        figure_number=1,
    )
    rendered = RenderedFigure(
        spec=spec,
        png_base64=base64.b64encode(b"png").decode("utf-8"),
        svg_content=None,
        latex_block="\\begin{figure}test\\end{figure}",
        latex_table=None,
        render_success=True,
        render_error=None,
    )
    once = injector.inject(text, [rendered])
    twice = injector.inject(once, [rendered])

    assert once == twice
    assert once.count("%% FIGURE_PLACEMENT: fig1") == 1
    assert "see Fig. 1" in once


def test_runtime_saves_assets_and_enriches_written_draft(tmp_path):
    settings = replace(get_settings(), local_projects_dir=tmp_path)

    class _StubExtractor:
        async def extract(self, written_draft, gemini_client):
            del gemini_client
            return [
                FigureSpec(
                    id="fig1",
                    type=FigureType.BAR_CHART,
                    section="results",
                    title="Accuracy chart",
                    caption="Fig. 1. Accuracy comparison.",
                    data={},
                    placement_hint="The system achieved 95% accuracy on the benchmark dataset.",
                    figure_number=1,
                )
            ]

    class _StubGenerator:
        async def render_all(self, specs):
            return [
                RenderedFigure(
                    spec=specs[0],
                    png_base64=base64.b64encode(b"png-bytes").decode("utf-8"),
                    svg_content=None,
                    latex_block="\\begin{figure}test\\end{figure}",
                    latex_table=None,
                    render_success=True,
                    render_error=None,
                )
            ]

    runtime = FigureTableRuntime(
        settings=settings,
        extractor=_StubExtractor(),
        generator=_StubGenerator(),
        injector=ManuscriptInjector(),
    )
    result = asyncio.run(
        runtime.execute(
            written_draft=_written_draft_payload(),
            gemini_client=None,
            project_id="project-123",
        )
    )

    assert result.figure_count == 1
    assert result.enriched_written_draft is not None
    expected_path = tmp_path / "project-123" / "generated_figures" / "fig1.png"
    assert expected_path.exists()


def test_merge_writing_with_figures_updates_written_draft_and_sections():
    writing_output = WritingAgentOutput(
        title="Visual Manuscript",
        abstract="Abstract text.",
        keywords=["IEEE"],
        sections=IEEESectionMap(
            introduction="Introduction text.",
            related_work="Related work text.",
            methodology="Methodology text.",
            results="The system achieved 95% accuracy on the benchmark dataset.",
            discussion="Discussion text.",
            limitations="Limitations text.",
            conclusion="Conclusion text.",
        ),
        references=["[1] Example."],
        written_draft=_written_draft_payload(),
    )
    figure_output = FigureTableAgentOutput(
        figures=[],
        tables=[],
        enriched_draft="",
        figure_count=0,
        table_count=0,
        extraction_metadata={},
        enriched_written_draft={
            **_written_draft_payload(),
            "abstract": {"section_name": "abstract", "text": "Updated abstract.", "confidence": 0.8},
            "sections": {
                **_written_draft_payload()["sections"],
                "results": {
                    "section_name": "results",
                    "text": "The system achieved 95% accuracy on the benchmark dataset (see Fig. 1).",
                    "confidence": 0.9,
                },
            },
        },
    )

    merged = _merge_writing_with_figures(
        writing_output=writing_output,
        figure_table_output=figure_output,
    )
    assert merged.abstract == "Updated abstract."
    assert "see Fig. 1" in merged.sections.results
    assert merged.written_draft["sections"]["results"]["text"].endswith("(see Fig. 1).")


def test_formatting_helper_injects_latex_blocks():
    latex = normalize_paragraphs_for_latex(
        "Results sentence.\n%% FIGURE_PLACEMENT: fig1",
        asset_map={
            "fig1": {
                "id": "fig1",
                "latex_block": "\\begin{figure}[!t]\\caption{Test}\\end{figure}",
            }
        },
    )
    assert "\\begin{figure}" in latex
    assert "Results sentence." in latex


def test_formatting_html_helper_handles_scalar_table_rows():
    from formatting.utils import _html_block_for_asset

    html = _html_block_for_asset(
        {
            "caption": "Table I. Scalar summary.",
            "spec": {
                "is_table": True,
                "data": {"headers": ["Metric", "Value"], "rows": [95, 93]},
            },
        }
    )
    assert "<table>" in html
    assert "95" in html


def test_dispatch_figure_table_stage_is_non_blocking_on_error():
    class _FailingManager:
        async def dispatch(self, **kwargs):
            del kwargs
            raise RuntimeError("stage boom")

    class _FakeFigureTableAgent:
        agent_name = "figure_table_agent"

    writing_output = WritingAgentOutput(
        title="Visual Manuscript",
        abstract="Abstract text.",
        keywords=["IEEE"],
        sections=IEEESectionMap(
            introduction="Introduction text.",
            related_work="Related work text.",
            methodology="Methodology text.",
            results="Results text.",
            discussion="Discussion text.",
            limitations="Limitations text.",
            conclusion="Conclusion text.",
        ),
        references=["[1] Example."],
        written_draft=_written_draft_payload(),
    )
    pipeline_context: dict[str, object] = {}

    output, duration_ms = asyncio.run(
        _dispatch_figure_table_stage(
            a2a_manager=_FailingManager(),
            figure_table_agent=_FakeFigureTableAgent(),
            writing_output=writing_output,
            project_id="project-123",
            trace_id="trace-123",
            pipeline_context=pipeline_context,
        )
    )

    assert duration_ms == 0.0
    assert output.figure_count == 0
    assert output.table_count == 0
    assert output.enriched_draft == ""
    assert pipeline_context["generated_figures"] == []
    assert pipeline_context["generated_tables"] == []


def test_save_project_generated_visuals_separates_generated_assets(monkeypatch, tmp_path):
    existing_project = ProjectRecord(
        id="project-123",
        file_name="paper.txt",
        file_path="paper.txt",
        extracted_text="source text",
        file_type="txt",
        file_size=10,
        extraction_time_ms=1.0,
        title="Visual Manuscript",
        owner_uid="user-123",
        owner_email="user@example.com",
        content="content",
        display_paper_text="content",
        latex_ready="content",
    )

    monkeypatch.setattr(project_service, "get_project", lambda project_id, owner_uid: existing_project)
    monkeypatch.setattr(project_service, "settings", replace(project_service.settings, local_projects_dir=tmp_path))
    persisted: dict[str, ProjectRecord] = {}

    def _fake_persist(project: ProjectRecord) -> ProjectRecord:
        persisted["project"] = project
        return project

    monkeypatch.setattr(project_service, "persist_project", _fake_persist)

    saved = project_service.save_project_generated_visuals(
        project_id="project-123",
        owner_uid="user-123",
        generated_figures=[
            {
                "spec": {"id": "fig1", "section": "results"},
                "render_success": True,
                "png_base64": base64.b64encode(b"png").decode("utf-8"),
            }
        ],
        generated_tables=[
            {
                "spec": {"id": "tab1", "section": "results"},
                "render_success": True,
            }
        ],
    )

    assert saved.figures == []
    assert saved.generated_figures[0]["spec"]["id"] == "fig1"
    assert saved.generated_tables[0]["spec"]["id"] == "tab1"
    assert saved.generated_figure_assets["fig1"].endswith("generated_figures/fig1.png") or saved.generated_figure_assets["fig1"].endswith("generated_figures\\fig1.png")
    assert persisted["project"].generated_figures == saved.generated_figures
