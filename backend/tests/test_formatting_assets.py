from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from pathlib import Path
import shutil
from uuid import uuid4

from formatting import agent as formatting_agent_module
from formatting.agent import run_formatting_pipeline
from formatting.config import FormattingConfig
from formatting.schemas import CompileReport, FormattedPaper, FormattingArtifacts
from formatting.utils import materialize_figure_assets
from core.config import get_settings
from models.generation import IEEESectionMap, ResearchPaperSchema


def _paper() -> ResearchPaperSchema:
    return ResearchPaperSchema(
        title="Visual Manuscript",
        abstract="This abstract is long enough to satisfy the formatter for testing purposes.",
        keywords=["IEEE", "visualization"],
        sections=IEEESectionMap(
            introduction="Introduction text.",
            related_work="Related work text.",
            methodology="Methodology text.",
            results="Results text with a generated figure marker.",
            discussion="Discussion text.",
            limitations="Limitations text.",
            conclusion="Conclusion text.",
        ),
        references=["[1] Example reference."],
    )


def _workspace_temp_dir() -> Path:
    work_dir = get_settings().base_dir / "verify-temp" / str(uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def test_materialize_figure_assets_writes_png_from_base64():
    work_dir = _workspace_temp_dir()
    try:
        diagnostics = materialize_figure_assets(
            figures={
                "results": [
                    {
                        "id": "fig1",
                        "path": "figures/fig1.png",
                        "png_base64": base64.b64encode(b"png-bytes").decode("utf-8"),
                    }
                ]
            },
            work_dir=work_dir,
        )

        assert diagnostics == []
        assert (work_dir / "figures" / "fig1.png").read_bytes() == b"png-bytes"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_run_formatting_pipeline_materializes_generated_figure_assets(monkeypatch):
    temp_dir = _workspace_temp_dir()
    try:
        settings = replace(get_settings(), temp_dir=temp_dir)
        config = replace(
            FormattingConfig.from_settings(settings),
            cleanup_workdir_on_success=False,
            cleanup_workdir_on_failure=False,
        )
        observed: dict[str, object] = {}

        def _fake_render_latex_document(*, context, config):
            del context, config
            return "\\documentclass{article}\\begin{document}ok\\end{document}"

        def _fake_generate_html_preview(*, context, config, work_dir):
            del context, config
            output_path = work_dir / "ieee-preview.html"
            output_path.write_text("<html></html>", encoding="utf-8")
            return "<html></html>", output_path

        def _fake_compile_latex_document(*, latex_source, html_preview, profile, config, work_dir):
            del latex_source, html_preview, config
            staged_path = work_dir / "figures" / "fig1.png"
            observed["staged_path"] = staged_path
            observed["staged_bytes"] = staged_path.read_bytes()
            return FormattedPaper(
                profile=profile,
                latex_source="latex",
                html_preview="<html></html>",
                artifacts=FormattingArtifacts(
                    work_dir=str(work_dir),
                    tex_path=str(work_dir / "ieee-paper.tex"),
                    pdf_path=str(work_dir / "ieee-paper.pdf"),
                    html_preview_path=str(work_dir / "ieee-preview.html"),
                ),
                compile_report=CompileReport(success=True, return_code=0, diagnostics=[]),
            )

        monkeypatch.setattr(formatting_agent_module, "render_latex_document", _fake_render_latex_document)
        monkeypatch.setattr(formatting_agent_module, "generate_html_preview", _fake_generate_html_preview)
        monkeypatch.setattr(formatting_agent_module, "compile_latex_document", _fake_compile_latex_document)

        result = asyncio.run(
            run_formatting_pipeline(
                paper=_paper(),
                figures={
                    "results": [
                        {
                            "id": "fig1",
                            "path": "figures/fig1.png",
                            "png_base64": base64.b64encode(b"png-bytes").decode("utf-8"),
                        }
                    ]
                },
                trace_id="trace-123",
                settings=settings,
                config=config,
            )
        )

        assert result.error is None
        assert observed["staged_path"].name == "fig1.png"
        assert observed["staged_path"].parent.name == "figures"
        assert observed["staged_bytes"] == b"png-bytes"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
