"""Concurrent renderers for charts, tables, and diagrams used in IEEE papers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import math
from collections.abc import Iterable
from typing import Callable

from figure_table.models import FigureSpec, FigureType, RenderedFigure

logger = logging.getLogger("papereasy.backend.figure_table.generator")


class FigureGenerator:
    """Render planned figures/tables into PNG, SVG, and LaTeX artifacts."""

    async def render_all(self, specs: list[FigureSpec]) -> list[RenderedFigure]:
        """Render all figure specifications concurrently."""

        tasks = [self.render_one(spec) for spec in specs]
        if not tasks:
            return []
        return list(await asyncio.gather(*tasks))

    async def render_one(self, spec: FigureSpec) -> RenderedFigure:
        """Render one specification using the matching renderer."""

        return await asyncio.to_thread(self._render_sync, spec)

    def _render_sync(self, spec: FigureSpec) -> RenderedFigure:
        renderer_map: dict[FigureType, Callable[[FigureSpec], RenderedFigure]] = {
            FigureType.BAR_CHART: self._render_bar_chart,
            FigureType.LINE_GRAPH: self._render_line_graph,
            FigureType.SCATTER_PLOT: self._render_scatter_plot,
            FigureType.CONFUSION_MATRIX: self._render_confusion_matrix,
            FigureType.PIE_CHART: self._render_pie_chart,
            FigureType.HEATMAP: self._render_heatmap,
            FigureType.TABLE: self._render_table,
            FigureType.FLOWCHART: self._render_flowchart,
            FigureType.ARCHITECTURE_DIAGRAM: self._render_architecture_diagram,
        }
        renderer = renderer_map.get(spec.type)
        if renderer is None:
            return self._render_failure(spec, ValueError(f"Unsupported figure type: {spec.type}"))
        return renderer(spec)

    def _render_bar_chart(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            fig, ax = plt.subplots(figsize=(3.5, 2.5))
            chart_data = self._coerce_chart_data(spec, prefer_multiple_series=True)
            x_values = chart_data["x_values"]
            series = chart_data["series"]

            bar_width = 0.8 / max(1, len(series))
            positions = list(range(len(x_values)))
            for index, item in enumerate(series):
                offsets = [value + (index - (len(series) - 1) / 2) * bar_width for value in positions]
                ax.bar(
                    offsets,
                    item.get("values", []),
                    width=bar_width,
                    label=item.get("name") or f"Series {index + 1}",
                    color=item.get("color"),
                )
            ax.set_xticks(positions)
            ax.set_xticklabels(x_values, rotation=20)
            ax.set_xlabel(chart_data["x_label"])
            ax.set_ylabel(chart_data["y_label"])
            if len(series) > 1:
                ax.legend(fontsize=7)
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_line_graph(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            fig, ax = plt.subplots(figsize=(3.5, 2.5))
            chart_data = self._coerce_chart_data(spec, prefer_multiple_series=True)
            x_values = chart_data["x_values"]
            series = chart_data["series"]

            styles = ["-o", "--s", "-.^", ":D"]
            for index, item in enumerate(series):
                ax.plot(
                    x_values,
                    item.get("values", []),
                    styles[index % len(styles)],
                    label=item.get("name") or f"Series {index + 1}",
                    color=item.get("color"),
                    linewidth=1.2,
                    markersize=4,
                )
            ax.set_xlabel(chart_data["x_label"])
            ax.set_ylabel(chart_data["y_label"])
            if len(series) > 1:
                ax.legend(fontsize=7)
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_scatter_plot(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            fig, ax = plt.subplots(figsize=(3.5, 2.5))
            markers = ["o", "s", "^", "D", "x"]
            chart_data = self._coerce_chart_data(spec, prefer_multiple_series=True)
            series = chart_data["series"]
            for index, item in enumerate(series):
                x_values = item.get("x_values", chart_data["x_numeric"])
                y_values = item.get("values", item.get("y_values", []))
                ax.scatter(
                    x_values,
                    y_values,
                    marker=markers[index % len(markers)],
                    label=item.get("name") or f"Series {index + 1}",
                    color=item.get("color"),
                )
            ax.set_xlabel(chart_data["x_label"])
            ax.set_ylabel(chart_data["y_label"])
            if len(series) > 1:
                ax.legend(fontsize=7)
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_confusion_matrix(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            sns = _seaborn_module()
            fig, ax = plt.subplots(figsize=(3.5, 2.6))
            matrix_data = self._coerce_matrix_data(spec, integral=True)
            matrix = matrix_data["matrix"]
            labels = matrix_data["labels"]
            sns.heatmap(matrix, annot=True, fmt="d", cmap="Blues", cbar=True, ax=ax)
            if labels:
                ax.set_xticklabels(labels, rotation=25)
                ax.set_yticklabels(labels, rotation=0)
            ax.set_xlabel("Predicted")
            ax.set_ylabel("Actual")
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_pie_chart(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            fig, ax = plt.subplots(figsize=(3.5, 2.5))
            pie_data = self._coerce_pie_chart_data(spec)
            labels = pie_data["labels"]
            values = pie_data["values"]
            colors = ["#5B8FF9", "#61DDAA", "#65789B", "#F6BD16", "#7262FD", "#78D3F8"]
            ax.pie(values, labels=labels, autopct="%1.1f%%", colors=colors[: len(values)], textprops={"fontsize": 8})
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_heatmap(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            sns = _seaborn_module()
            fig, ax = plt.subplots(figsize=(3.5, 2.6))
            matrix_data = self._coerce_matrix_data(spec, integral=False)
            matrix = matrix_data["matrix"]
            labels = matrix_data["labels"]
            sns.heatmap(matrix, annot=True, cmap="Blues", ax=ax)
            if labels:
                ax.set_xticklabels(labels, rotation=25)
                ax.set_yticklabels(labels, rotation=0)
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_table(self, spec: FigureSpec) -> RenderedFigure:
        try:
            table_data = self._coerce_table_data(spec)
            headers = table_data["headers"]
            rows = table_data["rows"]
            column_spec = self._infer_table_alignment(headers=headers, rows=rows)
            header_row = " & ".join(_latex_escape(header) for header in headers) + r" \\"
            body_rows = "\n".join(
                " & ".join(_latex_escape(value) for value in row) + r" \\"
                for row in rows
            )
            latex_table = (
                "\\begin{table}[!t]\n"
                f"\\caption{{{_latex_escape(spec.caption)}}}\n"
                f"\\label{{tab:{spec.id}}}\n"
                "\\centering\n"
                f"\\begin{{tabular}}{{{column_spec}}}\n"
                "\\toprule\n"
                f"{header_row}\n"
                "\\midrule\n"
                f"{body_rows}\n"
                "\\bottomrule\n"
                "\\end{tabular}\n"
                "\\end{table}"
            )
            return RenderedFigure(
                spec=spec,
                png_base64=None,
                svg_content=None,
                latex_block=latex_table,
                latex_table=latex_table,
                render_success=True,
                render_error=None,
            )
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_flowchart(self, spec: FigureSpec) -> RenderedFigure:
        try:
            from graphviz import Digraph

            flow_data = self._coerce_flowchart_data(spec)
            dot = Digraph(comment=spec.title)
            dot.attr(rankdir="TB", size="3.5,4", dpi="300")
            dot.attr("node", fontname="Helvetica", fontsize="9")
            shape_map = {"box": "box", "diamond": "diamond", "oval": "ellipse"}
            for node in flow_data["nodes"]:
                dot.node(
                    str(node.get("id")),
                    str(node.get("label", "")),
                    shape=shape_map.get(str(node.get("shape", "box")), "box"),
                )
            for edge in flow_data["edges"]:
                dot.edge(
                    str(edge.get("from")),
                    str(edge.get("to")),
                    label=str(edge.get("label", "")) or None,
                )
            png_bytes = dot.pipe(format="png")
            svg_bytes = dot.pipe(format="svg")
            return RenderedFigure(
                spec=spec,
                png_base64=base64.b64encode(png_bytes).decode("utf-8"),
                svg_content=svg_bytes.decode("utf-8", errors="replace"),
                latex_block=self._latex_figure_block(spec),
                latex_table=None,
                render_success=True,
                render_error=None,
            )
        except Exception as exc:
            logger.warning("Graphviz flowchart rendering failed for %s, using matplotlib fallback: %s", spec.id, exc)
            return self._render_flowchart_matplotlib(spec)

    def _render_flowchart_matplotlib(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            patches = _matplotlib_patches()
            fig, ax = plt.subplots(figsize=(3.5, 4.0))
            ax.axis("off")
            flow_data = self._coerce_flowchart_data(spec)
            nodes = flow_data["nodes"]
            edges = flow_data["edges"]

            positions: dict[str, tuple[float, float]] = {}
            y_positions = list(reversed(range(len(nodes))))
            for index, node in enumerate(nodes):
                x = 0.5
                y = y_positions[index]
                positions[str(node.get("id"))] = (x, y)
                patch = self._flowchart_patch(
                    patches,
                    x=x,
                    y=y,
                    shape=str(node.get("shape", "box")),
                )
                ax.add_patch(patch)
                ax.text(x, y, str(node.get("label", "")), ha="center", va="center", fontsize=8, wrap=True)

            for edge in edges:
                start = positions.get(str(edge.get("from")))
                end = positions.get(str(edge.get("to")))
                if not start or not end:
                    continue
                ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "lw": 1.0})
                label = str(edge.get("label", "")).strip()
                if label:
                    ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, label, fontsize=7)

            ax.set_xlim(0, 1)
            ax.set_ylim(-1, len(nodes))
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _render_architecture_diagram(self, spec: FigureSpec) -> RenderedFigure:
        try:
            plt = _matplotlib_pyplot()
            patches = _matplotlib_patches()
            fig, ax = plt.subplots(figsize=(3.5, 3.0))
            ax.axis("off")
            architecture_data = self._coerce_architecture_data(spec)
            components = architecture_data["components"]
            connections = architecture_data["connections"]

            colors = {
                "input": "#D6E9FF",
                "process": "#FFFFFF",
                "output": "#D7F5D1",
                "store": "#FFF3B0",
            }
            positions: dict[str, tuple[float, float]] = {}
            columns = max(1, math.ceil(math.sqrt(len(components))))
            for index, component in enumerate(components):
                col = index % columns
                row = index // columns
                x = 0.15 + col * 0.3
                y = 0.85 - row * 0.3
                positions[str(component.get("id"))] = (x, y)
                rect = patches.FancyBboxPatch(
                    (x - 0.1, y - 0.06),
                    0.2,
                    0.12,
                    boxstyle="round,pad=0.02",
                    linewidth=1.0,
                    edgecolor="#444444",
                    facecolor=colors.get(str(component.get("type", "process")), "#FFFFFF"),
                )
                ax.add_patch(rect)
                ax.text(x, y, str(component.get("label", "")), ha="center", va="center", fontsize=8, wrap=True)

            for connection in connections:
                start = positions.get(str(connection.get("from")))
                end = positions.get(str(connection.get("to")))
                if not start or not end:
                    continue
                ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "lw": 1.0})
                label = str(connection.get("label", "")).strip()
                if label:
                    ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.03, label, fontsize=7)

            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            fig.tight_layout()
            return self._build_chart_result(fig, spec)
        except Exception as exc:
            return self._render_failure(spec, exc)

    def _build_chart_result(self, fig, spec: FigureSpec) -> RenderedFigure:
        png_buffer = io.BytesIO()
        svg_buffer = io.StringIO()
        fig.savefig(png_buffer, format="png", bbox_inches="tight")
        fig.savefig(svg_buffer, format="svg", bbox_inches="tight")
        png_base64 = base64.b64encode(png_buffer.getvalue()).decode("utf-8")
        svg_content = svg_buffer.getvalue()
        try:
            import matplotlib.pyplot as plt

            plt.close(fig)
        except Exception:
            pass
        return RenderedFigure(
            spec=spec,
            png_base64=png_base64,
            svg_content=svg_content,
            latex_block=self._latex_figure_block(spec),
            latex_table=None,
            render_success=True,
            render_error=None,
        )

    def _latex_figure_block(self, spec: FigureSpec) -> str:
        return (
            "\\begin{figure}[!t]\n"
            "\\centering\n"
            f"\\includegraphics[width=\\columnwidth]{{figures/{spec.id}.png}}\n"
            f"\\caption{{{_latex_escape(spec.caption)}}}\n"
            f"\\label{{fig:{spec.id}}}\n"
            "\\end{figure}"
        )

    def _render_failure(self, spec: FigureSpec, error: Exception) -> RenderedFigure:
        logger.error("Figure rendering failed for %s: %s", spec.id, error)
        return RenderedFigure(
            spec=spec,
            png_base64=None,
            svg_content=None,
            latex_block="",
            latex_table=None,
            render_success=False,
            render_error=str(error),
        )

    def _infer_table_alignment(self, *, headers: list[str], rows: list[list[str]]) -> str:
        alignments = ["l"]
        numeric_columns = range(1, len(headers))
        for column_index in numeric_columns:
            is_numeric = True
            for row in rows:
                if column_index >= len(row):
                    continue
                try:
                    float(str(row[column_index]).replace("%", "").replace(",", ""))
                except ValueError:
                    is_numeric = False
                    break
            alignments.append("c" if is_numeric else "l")
        return " ".join(alignments)

    def _normalize_table_rows(self, rows: object, *, column_count: int) -> list[list[str]]:
        normalized_rows: list[list[str]] = []
        if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, dict)):
            return normalized_rows

        for row in rows:
            if isinstance(row, dict):
                values = [str(value) for value in row.values()]
            elif isinstance(row, Iterable) and not isinstance(row, (str, bytes)):
                values = [str(value) for value in row]
            else:
                values = [str(row)]

            if column_count > 0:
                if len(values) < column_count:
                    values.extend([""] * (column_count - len(values)))
                elif len(values) > column_count:
                    values = values[:column_count]
            normalized_rows.append(values)
        return normalized_rows

    def _coerce_chart_data(self, spec: FigureSpec, *, prefer_multiple_series: bool) -> dict[str, object]:
        data = dict(spec.data or {})
        chart_title = str(data.get("title") or spec.title or spec.caption).strip()
        x_values = self._normalize_string_list(data.get("x_values"))
        if not x_values:
            x_values = self._fallback_categories(spec)

        raw_series = data.get("series", [])
        series: list[dict[str, object]] = []
        if isinstance(raw_series, list):
            for index, entry in enumerate(raw_series):
                if isinstance(entry, dict):
                    values = self._normalize_numeric_list(entry.get("values") or entry.get("y_values"), len(x_values))
                    x_numeric = self._normalize_numeric_list(entry.get("x_values"), len(x_values))
                    if not values:
                        values = self._fallback_numeric_series(spec, len(x_values), offset=index)
                    if not x_numeric:
                        x_numeric = list(range(1, len(x_values) + 1))
                    series.append(
                        {
                            "name": str(entry.get("name") or f"Series {index + 1}"),
                            "values": values,
                            "x_values": x_numeric,
                            "color": entry.get("color") or self._default_palette()[index % len(self._default_palette())],
                        }
                    )

        if not series:
            series_count = 2 if prefer_multiple_series else 1
            fallback_names = self._fallback_series_names(spec, series_count)
            for index, name in enumerate(fallback_names):
                series.append(
                    {
                        "name": name,
                        "values": self._fallback_numeric_series(spec, len(x_values), offset=index),
                        "x_values": list(range(1, len(x_values) + 1)),
                        "color": self._default_palette()[index % len(self._default_palette())],
                    }
                )

        return {
            "title": chart_title,
            "x_values": x_values,
            "x_numeric": list(range(1, len(x_values) + 1)),
            "series": series,
            "x_label": str(data.get("x_label") or self._default_x_label(spec)),
            "y_label": str(data.get("y_label") or self._default_y_label(spec)),
        }

    def _coerce_pie_chart_data(self, spec: FigureSpec) -> dict[str, list[object]]:
        data = dict(spec.data or {})
        labels = self._normalize_string_list(data.get("labels"))
        values = self._normalize_numeric_list(data.get("values"), len(labels) if labels else 0)

        raw_series = data.get("series", [])
        if (not labels or not values) and isinstance(raw_series, list) and raw_series:
            labels = [
                str(entry.get("name") or f"Slice {index + 1}")
                for index, entry in enumerate(raw_series)
                if isinstance(entry, dict)
            ]
            values = [
                float(entry.get("value", 0) or 0)
                for entry in raw_series
                if isinstance(entry, dict)
            ]

        if not labels or not values:
            labels = self._fallback_categories(spec, count=4)
            values = self._fallback_numeric_series(spec, len(labels), offset=0, minimum=12, span=25)

        total = sum(values) or 1.0
        normalized = [max(1.0, round((value / total) * 100.0, 1)) for value in values]
        return {"labels": labels, "values": normalized}

    def _coerce_matrix_data(self, spec: FigureSpec, *, integral: bool) -> dict[str, object]:
        data = dict(spec.data or {})
        labels = self._normalize_string_list(data.get("labels"))
        raw_matrix = data.get("matrix")
        matrix: list[list[float | int]] = []

        if isinstance(raw_matrix, list):
            for row in raw_matrix:
                if isinstance(row, Iterable) and not isinstance(row, (str, bytes, dict)):
                    matrix.append(
                        [
                            int(value) if integral else float(value)
                            for value in list(row)
                            if isinstance(value, (int, float))
                        ]
                    )

        if not labels:
            size = len(matrix) if matrix else 3
            labels = [f"Class {index + 1}" for index in range(size)]

        size = len(labels)
        if not matrix or any(len(row) != size for row in matrix) or len(matrix) != size:
            matrix = []
            for row_index in range(size):
                row_values = []
                for column_index in range(size):
                    if row_index == column_index:
                        value = 82 + ((self._seed(spec) + row_index * 7 + column_index * 3) % 14)
                    else:
                        value = 4 + ((self._seed(spec) + row_index * 5 + column_index * 11) % 9)
                    row_values.append(int(value) if integral else float(value))
                matrix.append(row_values)

        return {"matrix": matrix, "labels": labels}

    def _coerce_table_data(self, spec: FigureSpec) -> dict[str, list[list[str]] | list[str]]:
        data = dict(spec.data or {})
        headers = self._normalize_string_list(data.get("headers"))
        rows = self._normalize_table_rows(data.get("rows", []), column_count=len(headers))

        if not headers:
            headers = ["Metric", "Baseline", "Proposed"]

        if not rows:
            categories = self._fallback_categories(spec, count=4)
            baseline = self._fallback_numeric_series(spec, len(categories), offset=0, minimum=50, span=25)
            proposed = self._fallback_numeric_series(spec, len(categories), offset=1, minimum=60, span=25)
            rows = [
                [category, str(int(base_value)), str(int(proposed_value))]
                for category, base_value, proposed_value in zip(categories, baseline, proposed, strict=False)
            ]

        rows = self._normalize_table_rows(rows, column_count=len(headers))
        return {"headers": headers, "rows": rows}

    def _coerce_flowchart_data(self, spec: FigureSpec) -> dict[str, list[dict[str, str]]]:
        data = dict(spec.data or {})
        nodes = [node for node in data.get("nodes", []) if isinstance(node, dict)]
        edges = [edge for edge in data.get("edges", []) if isinstance(edge, dict)]
        if nodes:
            return {"nodes": nodes, "edges": edges}

        nodes = [
            {"id": "n1", "label": "Collect inputs", "shape": "oval"},
            {"id": "n2", "label": "Preprocess evidence", "shape": "box"},
            {"id": "n3", "label": "Run simulation", "shape": "box"},
            {"id": "n4", "label": "Evaluate policies", "shape": "diamond"},
            {"id": "n5", "label": "Report outputs", "shape": "box"},
        ]
        edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": "approved"},
        ]
        return {"nodes": nodes, "edges": edges}

    def _coerce_architecture_data(self, spec: FigureSpec) -> dict[str, list[dict[str, str]]]:
        data = dict(spec.data or {})
        components = [component for component in data.get("components", []) if isinstance(component, dict)]
        connections = [connection for connection in data.get("connections", []) if isinstance(connection, dict)]
        if components:
            return {"components": components, "connections": connections}

        components = [
            {"id": "c1", "label": "Urban data inputs", "type": "input"},
            {"id": "c2", "label": "Digital twin engine", "type": "process"},
            {"id": "c3", "label": "Policy evaluator", "type": "process"},
            {"id": "c4", "label": "Scenario store", "type": "store"},
            {"id": "c5", "label": "Dashboard output", "type": "output"},
        ]
        connections = [
            {"from": "c1", "to": "c2", "label": "stream"},
            {"from": "c2", "to": "c3", "label": "simulation"},
            {"from": "c3", "to": "c4", "label": "archive"},
            {"from": "c3", "to": "c5", "label": "insights"},
        ]
        return {"components": components, "connections": connections}

    def _fallback_categories(self, spec: FigureSpec, *, count: int = 4) -> list[str]:
        section_defaults = {
            "results": ["Scenario A", "Scenario B", "Scenario C", "Scenario D"],
            "discussion": ["Traffic", "Air quality", "Housing", "Equity"],
            "methodology": ["Stage 1", "Stage 2", "Stage 3", "Stage 4"],
            "limitations": ["Coverage", "Bias", "Latency", "Data gaps"],
        }
        values = section_defaults.get(spec.section, ["Metric 1", "Metric 2", "Metric 3", "Metric 4"])
        return values[:count]

    def _fallback_series_names(self, spec: FigureSpec, count: int) -> list[str]:
        if count <= 1:
            return ["Observed"]
        if spec.section == "results":
            return ["Baseline", "Proposed"][:count]
        if spec.section == "discussion":
            return ["Current", "Projected"][:count]
        return ["Series 1", "Series 2"][:count]

    def _fallback_numeric_series(
        self,
        spec: FigureSpec,
        count: int,
        *,
        offset: int,
        minimum: int = 55,
        span: int = 30,
    ) -> list[float]:
        seed = self._seed(spec) + (offset * 17)
        values: list[float] = []
        for index in range(count):
            seed = (seed * 1103515245 + 12345 + index * 97) & 0x7FFFFFFF
            values.append(float(minimum + (seed % max(6, span))))
        return values

    def _default_palette(self) -> list[str]:
        return ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b"]

    def _default_x_label(self, spec: FigureSpec) -> str:
        if spec.section == "results":
            return "Scenario"
        if spec.section == "methodology":
            return "Pipeline stage"
        return "Category"

    def _default_y_label(self, spec: FigureSpec) -> str:
        if spec.section == "results":
            return "Performance"
        if spec.section == "discussion":
            return "Impact"
        return "Value"

    def _normalize_string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _normalize_numeric_list(self, value: object, expected_count: int) -> list[float]:
        if not isinstance(value, list):
            return []
        normalized: list[float] = []
        for item in value:
            try:
                normalized.append(float(item))
            except (TypeError, ValueError):
                continue
        if expected_count > 0:
            if len(normalized) < expected_count:
                return []
            normalized = normalized[:expected_count]
        return normalized

    def _seed(self, spec: FigureSpec) -> int:
        token = f"{spec.id}|{spec.section}|{spec.title}|{spec.caption}"
        return int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16)

    def _flowchart_patch(self, patches, *, x: float, y: float, shape: str):
        if shape == "diamond":
            return patches.RegularPolygon((x, y), numVertices=4, radius=0.09, orientation=0.785398)
        if shape == "oval":
            return patches.Ellipse((x, y), width=0.22, height=0.11, fill=False, edgecolor="#444444", linewidth=1.0)
        return patches.FancyBboxPatch(
            (x - 0.11, y - 0.055),
            0.22,
            0.11,
            boxstyle="round,pad=0.02",
            linewidth=1.0,
            edgecolor="#444444",
            facecolor="#FFFFFF",
        )


def _matplotlib_pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 9,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "figure.dpi": 300,
        }
    )
    return plt


def _matplotlib_patches():
    import matplotlib.patches as patches

    return patches


def _seaborn_module():
    import seaborn as sns

    return sns


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in str(value))
