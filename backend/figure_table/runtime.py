"""End-to-end runtime for extracting, rendering, and injecting generated figures/tables."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from app.services.paper_service import build_editor_display_text, parse_editor_content
from core.config import Settings, get_settings
from figure_table.extractor import FigureExtractor
from figure_table.generator import FigureGenerator
from figure_table.injector import ManuscriptInjector
from figure_table.models import FigureTableOutput, RenderedFigure
from models.generation import ResearchPaperSchema
from writing.schemas import WrittenPaperDraft, build_paper_snapshot

logger = logging.getLogger("papereasy.backend.figure_table.runtime")


class FigureTableRuntime:
    """Run figure extraction, rendering, injection, and asset persistence."""

    def __init__(
        self,
        gemini_client=None,
        *,
        settings: Settings | None = None,
        extractor: FigureExtractor | None = None,
        generator: FigureGenerator | None = None,
        injector: ManuscriptInjector | None = None,
    ):
        self.gemini_client = gemini_client
        self.settings = settings or get_settings()
        self.extractor = extractor or FigureExtractor()
        self.generator = generator or FigureGenerator()
        self.injector = injector or ManuscriptInjector()

    async def execute(
        self,
        written_draft: object,
        gemini_client=None,
        project_id: str = "",
        paper_snapshot: object | None = None,
    ) -> FigureTableOutput:
        """Extract, render, inject, and persist generated figures for a manuscript."""

        parsed_written_draft = self._parse_written_draft(written_draft)
        if parsed_written_draft is None:
            logger.warning("FigureTableRuntime received no usable written_draft payload.")
            return FigureTableOutput(
                figures=None,
                tables=None,
                extraction_metadata={"status": "missing_written_draft"},
                status="skipped",
            )

        resolved_paper = self._resolve_paper_snapshot(
            paper_snapshot=paper_snapshot,
            written_draft=parsed_written_draft,
        )
        manuscript_text = build_editor_display_text(resolved_paper)

        specs = await self.extractor.extract(
            manuscript_text,
            gemini_client or self.gemini_client,
        )
        rendered = await self.generator.render_all(specs)
        enriched_draft = self.injector.inject(manuscript_text, rendered)
        asset_paths = self._persist_rendered_assets(project_id=project_id, rendered=rendered)
        figures = [item for item in rendered if not item.spec.is_table]
        tables = [item for item in rendered if item.spec.is_table]
        enriched_written_draft = None
        status = "succeeded"
        error = None

        try:
            enriched_written_draft = self._build_enriched_written_draft(
                original=parsed_written_draft,
                enriched_draft=enriched_draft,
                source_paper=resolved_paper,
            )
        except Exception as exc:
            logger.warning("Figure enrichment rebuild incomplete; keeping generated visuals: %s", exc)
            status = "partial"
            error = str(exc)

        return FigureTableOutput(
            figures=figures,
            tables=tables,
            enriched_draft=enriched_draft,
            figure_count=len(figures),
            table_count=len(tables),
            extraction_metadata={
                "status": "ok",
                "spec_count": len(specs),
                "rendered_count": len(rendered),
                "rendered_success_count": len([item for item in rendered if item.render_success]),
                "asset_paths": asset_paths,
            },
            enriched_written_draft=(
                enriched_written_draft.model_dump(mode="python") if enriched_written_draft is not None else None
            ),
            status=status,
            error=error,
        )

    def _parse_written_draft(self, written_draft: object) -> WrittenPaperDraft | None:
        if written_draft in (None, "", {}):
            return None
        try:
            return WrittenPaperDraft.model_validate(written_draft)
        except Exception as exc:
            logger.warning("Unable to parse written_draft for figure extraction: %s", exc)
            return None

    def _resolve_paper_snapshot(
        self,
        *,
        paper_snapshot: object | None,
        written_draft: WrittenPaperDraft,
    ) -> ResearchPaperSchema:
        if paper_snapshot not in (None, "", {}):
            try:
                return ResearchPaperSchema.model_validate(paper_snapshot)
            except Exception as exc:
                logger.warning("Invalid paper snapshot for figure extraction; rebuilding from written draft: %s", exc)

        return build_paper_snapshot(
            title=written_draft.title,
            abstract=written_draft.abstract.text,
            keywords=list(written_draft.metadata.get("keywords", [])),
            sections=written_draft.sections,
            references=list(written_draft.metadata.get("references", [])),
        )

    def _build_enriched_written_draft(
        self,
        *,
        original: WrittenPaperDraft,
        enriched_draft: str,
        source_paper: ResearchPaperSchema,
    ) -> WrittenPaperDraft:
        enriched_paper = parse_editor_content(
            title=source_paper.title,
            content=enriched_draft,
            fallback_keywords=source_paper.keywords,
            fallback_references=source_paper.references,
            fallback_paper=source_paper,
            mode="figure_table",
        )

        updated_sections = {
            section_name: original.sections[section_name].model_copy(
                update={"text": getattr(enriched_paper.sections, section_name)}
            )
            for section_name in original.sections
        }
        return original.model_copy(
            update={
                "abstract": original.abstract.model_copy(update={"text": enriched_paper.abstract}),
                "sections": updated_sections,
                "metadata": {
                    **original.metadata,
                    "keywords": enriched_paper.keywords,
                    "references": enriched_paper.references,
                    "figure_enriched": True,
                },
            }
        )

    def _persist_rendered_assets(self, *, project_id: str, rendered: list[RenderedFigure]) -> dict[str, str]:
        if not project_id:
            return {}

        asset_dir = self.settings.local_projects_dir / project_id / "generated_figures"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_paths: dict[str, str] = {}
        for entry in rendered:
            if not entry.render_success or not entry.png_base64:
                continue
            target_path = asset_dir / f"{entry.spec.id}.png"
            try:
                target_path.write_bytes(base64.b64decode(entry.png_base64))
            except Exception as exc:
                logger.warning("Unable to persist rendered figure %s: %s", entry.spec.id, exc)
                continue
            asset_paths[entry.spec.id] = str(target_path)
        return asset_paths
