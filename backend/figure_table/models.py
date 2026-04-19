"""Pydantic models and helper utilities for generated manuscript visuals."""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FigureType(str, Enum):
    BAR_CHART = "bar_chart"
    LINE_GRAPH = "line_graph"
    SCATTER_PLOT = "scatter_plot"
    TABLE = "table"
    FLOWCHART = "flowchart"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"
    CONFUSION_MATRIX = "confusion_matrix"
    PIE_CHART = "pie_chart"
    HEATMAP = "heatmap"


_SECTION_ALIAS_MAP = {
    "abstract": "abstract",
    "intro": "introduction",
    "introduction": "introduction",
    "related work": "related_work",
    "related works": "related_work",
    "background": "related_work",
    "literature review": "related_work",
    "method": "methodology",
    "methods": "methodology",
    "methodology": "methodology",
    "approach": "methodology",
    "materials methods": "methodology",
    "materials and methods": "methodology",
    "experimental setup": "methodology",
    "system architecture": "methodology",
    "results": "results",
    "result": "results",
    "evaluation": "results",
    "experiments": "results",
    "experimental results": "results",
    "findings": "results",
    "discussion": "discussion",
    "analysis": "discussion",
    "limitations": "limitations",
    "limitation": "limitations",
    "threats to validity": "limitations",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "future work": "conclusion",
}


def normalize_section_name(value: object) -> str:
    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("&", " and ")
        .replace("/", " and ")
    )
    normalized = " ".join(normalized.split())
    return _SECTION_ALIAS_MAP.get(normalized, normalized.replace(" ", "_"))


class FigureSpec(BaseModel):
    """Planning-time specification for one generated figure or table."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    type: FigureType
    section: str
    title: str
    caption: str
    data: dict[str, Any] = Field(default_factory=dict)
    placement_hint: str
    figure_number: int | None = None
    table_number: int | None = None
    is_table: bool = False

    @field_validator("section", mode="before")
    @classmethod
    def normalize_section(cls, value: object) -> str:
        return normalize_section_name(value)


class RenderedFigure(BaseModel):
    """Rendered artifact bundle for a planned figure or table."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: FigureSpec
    png_base64: str | None = None
    svg_content: str | None = None
    latex_block: str
    latex_table: str | None = None
    render_success: bool
    render_error: str | None = None


class FigureTableOutput(BaseModel):
    """Runtime result for generated manuscript visuals."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    figures: list[RenderedFigure] | None = None
    tables: list[RenderedFigure] | None = None
    enriched_draft: str = ""
    figure_count: int = 0
    table_count: int = 0
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
    enriched_written_draft: dict[str, Any] | None = None
    status: Literal["succeeded", "partial", "failed", "skipped"] = "succeeded"
    error: str | None = None


def figure_reference_label(spec: FigureSpec) -> str:
    """Return the in-text label for a generated figure or table."""

    if spec.is_table:
        numeral = _to_roman(spec.table_number or 1)
        return f"Table {numeral}"
    return f"Fig. {spec.figure_number or 1}"


def figure_section_groups(
    entries: Iterable[RenderedFigure],
) -> dict[str, list[RenderedFigure]]:
    """Group rendered entries by IEEE section name."""

    grouped: dict[str, list[RenderedFigure]] = {}
    for entry in entries:
        grouped.setdefault(entry.spec.section, []).append(entry)
    return grouped


def _to_roman(number: int) -> str:
    values = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    remainder = max(1, int(number))
    parts: list[str] = []
    for arabic, roman in values:
        while remainder >= arabic:
            parts.append(roman)
            remainder -= arabic
    return "".join(parts)
