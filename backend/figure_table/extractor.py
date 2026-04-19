"""Gemini-backed extraction of figure, table, and chart plans from manuscript drafts."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from figure_table.models import FigureSpec, FigureType

logger = logging.getLogger("papereasy.backend.figure_table.extractor")

_SYSTEM_PROMPT_TEMPLATE = """SYSTEM: You are an IEEE research paper figure planning expert. Analyze the 
provided paper draft and identify ALL data, comparisons, results, processes, 
and system descriptions that should be visualized as figures or tables in a 
complete IEEE paper. 
  
Return ONLY a valid JSON object with no markdown, no explanation, no backticks.
  
JSON format:
{
  "figures": [
    {
      "id": "fig1",
      "type": "bar_chart|line_graph|scatter_plot|table|flowchart|
               architecture_diagram|confusion_matrix|pie_chart|heatmap",
      "section": "introduction|related_work|methodology|results|
                  discussion|limitations|conclusion",
      "title": "Short descriptive title",
      "caption": "Fig. N. Full IEEE-style caption ending with period.",
      "is_table": false,
      "placement_hint": "Exact sentence from the paper after which to place this",
      "data": {
        // For bar_chart/line_graph/scatter_plot:
        "x_label": "...",
        "y_label": "...",
        "x_values": [...],
        "series": [
          {"name": "Method A", "values": [...], "color": "#2196F3"},
          {"name": "Method B", "values": [...], "color": "#FF5722"}
        ],
        "title": "...",
        
        // For table:
        "headers": ["Column1", "Column2", ...],
        "rows": [["val1", "val2", ...], ...],
        "bold_header": true,
        
        // For flowchart:
        "nodes": [
          {"id": "n1", "label": "...", "shape": "box|diamond|oval"}
        ],
        "edges": [
          {"from": "n1", "to": "n2", "label": "optional edge label"}
        ],
        
        // For confusion_matrix/heatmap:
        "matrix": [[...], [...]],
        "labels": ["Class A", "Class B", ...],
        
        // For architecture_diagram:
        "components": [
          {"id": "c1", "label": "...", "type": "input|process|output|store"}
        ],
        "connections": [
          {"from": "c1", "to": "c2", "label": "..."}
        ]
      }
    }
  ]
}
  
Rules:
- Generate between 4 and 8 figures/tables total
- Every results section MUST have at least one chart and one table
- Every methodology section MUST have a flowchart or architecture diagram
- Use realistic data values consistent with the paper content
- Assign sequential fig/table numbers separately (fig1,fig2 and tab1,tab2)
- Tables get is_table: true and caption "Table I." style (Roman numerals)

PAPER DRAFT:
<<WRITTEN_DRAFT>>
"""


class _FigurePlanItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(min_length=1)
    type: FigureType
    section: str = Field(min_length=1)
    title: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    placement_hint: str = Field(min_length=1)
    is_table: bool = False


class _FigurePlanResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    figures: list[_FigurePlanItem] = Field(default_factory=list)


class FigureExtractor:
    """Extract figure and table specifications from the written manuscript."""

    async def extract(self, written_draft: str, gemini_client) -> list[FigureSpec]:
        """Return parsed figure specifications or an empty list on failure."""

        normalized_draft = str(written_draft or "").strip()
        if not normalized_draft:
            logger.warning("Figure extractor received an empty manuscript draft.")
            return []

        if gemini_client is None:
            logger.warning("Figure extractor has no Gemini client; skipping extraction.")
            return []

        try:
            response = await gemini_client.generate_json(
                prompt=_SYSTEM_PROMPT_TEMPLATE.replace("<<WRITTEN_DRAFT>>", normalized_draft),
                response_schema=_FigurePlanResponse,
            )
        except Exception as exc:
            logger.error("Figure extraction failed: %s", exc)
            return []

        try:
            specs = [
                FigureSpec(
                    id=item.id.strip(),
                    type=item.type,
                    section=item.section.strip().lower(),
                    title=item.title.strip(),
                    caption=item.caption.strip(),
                    data=dict(item.data or {}),
                    placement_hint=item.placement_hint.strip(),
                    is_table=bool(item.is_table or item.type == FigureType.TABLE),
                )
                for item in response.figures
            ]
        except ValidationError as exc:
            logger.error("Figure extraction returned invalid JSON payload: %s", exc)
            return []

        return self._assign_numbers(specs)

    def _assign_numbers(self, specs: list[FigureSpec]) -> list[FigureSpec]:
        figure_counter = 1
        table_counter = 1
        normalized_specs: list[FigureSpec] = []
        for spec in specs:
            updates: dict[str, Any] = {}
            if spec.is_table or spec.type == FigureType.TABLE:
                updates["id"] = f"tab{table_counter}"
                updates["table_number"] = table_counter
                updates["figure_number"] = None
                if not spec.caption.lower().startswith("table"):
                    updates["caption"] = f"Table {_to_roman(table_counter)}. {spec.caption.rstrip('.')}."
                table_counter += 1
            else:
                updates["id"] = f"fig{figure_counter}"
                updates["figure_number"] = figure_counter
                updates["table_number"] = None
                if not spec.caption.lower().startswith("fig."):
                    updates["caption"] = f"Fig. {figure_counter}. {spec.caption.rstrip('.')}."
                figure_counter += 1
            normalized_specs.append(spec.model_copy(update=updates))
        return normalized_specs


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
    result: list[str] = []
    for arabic, roman in values:
        while remainder >= arabic:
            result.append(roman)
            remainder -= arabic
    return "".join(result)
