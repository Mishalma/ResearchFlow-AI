from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings, get_settings
from formatting.schemas import FormattingProfile


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class FormattingConfig:
    profile_name: str = "ieee_conference_us_letter"
    paper_size: str = "us_letter"
    template_dir: Path | None = None
    support_asset_dir: Path | None = None
    pdflatex_command: str = "pdflatex"
    compiler_timeout_seconds: int = 60
    compile_passes: int = 2
    cleanup_workdir_on_success: bool = False
    cleanup_workdir_on_failure: bool = False
    html_preview_file_name: str = "ieee-preview.html"
    latex_file_name: str = "ieee-paper.tex"
    abstract_min_words: int = 150
    abstract_max_words: int = 250
    diagnostic_excerpt_lines: int = 20
    sort_index_terms: bool = True
    debug_logging: bool = False

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "FormattingConfig":
        resolved_settings = settings or get_settings()
        paper_size = os.getenv("FORMATTING_PAPER_SIZE", "us_letter").strip().lower() or "us_letter"
        if paper_size not in {"us_letter", "a4"}:
            paper_size = "us_letter"
        profile_name = f"ieee_conference_{paper_size}"
        return cls(
            profile_name=profile_name,
            paper_size=paper_size,
            template_dir=resolved_settings.base_dir / "formatting" / "templates",
            support_asset_dir=resolved_settings.templates_dir,
            pdflatex_command=resolved_settings.pdflatex_command,
            compiler_timeout_seconds=resolved_settings.pdflatex_timeout_seconds,
            compile_passes=max(1, _get_int("FORMATTING_COMPILE_PASSES", 2)),
            cleanup_workdir_on_success=_get_bool("FORMATTING_CLEANUP_ON_SUCCESS", False),
            cleanup_workdir_on_failure=_get_bool("FORMATTING_CLEANUP_ON_FAILURE", False),
            abstract_min_words=max(50, _get_int("FORMATTING_ABSTRACT_MIN_WORDS", 150)),
            abstract_max_words=max(100, _get_int("FORMATTING_ABSTRACT_MAX_WORDS", 250)),
            sort_index_terms=_get_bool("FORMATTING_SORT_INDEX_TERMS", True),
            debug_logging=_get_bool("FORMATTING_DEBUG_LOGGING", resolved_settings.debug),
        )

    def build_profile(self) -> FormattingProfile:
        if self.paper_size == "a4":
            return FormattingProfile(
                profile_name=self.profile_name,
                paper_size="a4",
                top_margin_mm=19.0,
                bottom_margin_mm=43.0,
                left_margin_mm=13.0,
                right_margin_mm=13.0,
                column_gap_mm=4.0,
                column_width_mm=88.0,
                body_font_pt=10.0,
                title_font_pt=24.0,
                author_font_pt=11.0,
                affiliation_font_pt=10.0,
                email_font_pt=9.0,
                paragraph_indent_mm=3.5,
                two_column=True,
                sort_index_terms=self.sort_index_terms,
            )
        return FormattingProfile(
            profile_name=self.profile_name,
            paper_size="us_letter",
            top_margin_mm=19.05,
            bottom_margin_mm=25.4,
            left_margin_mm=15.875,
            right_margin_mm=15.875,
            column_gap_mm=6.35,
            column_width_mm=88.9,
            body_font_pt=10.0,
            title_font_pt=24.0,
            author_font_pt=11.0,
            affiliation_font_pt=10.0,
            email_font_pt=9.0,
            paragraph_indent_mm=3.5,
            two_column=True,
            sort_index_terms=self.sort_index_terms,
        )
