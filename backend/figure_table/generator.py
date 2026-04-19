"""Concurrent renderers for charts, tables, and diagrams used in IEEE papers."""

from __future__ import annotations

import asyncio
import base64
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
            x_values = [str(value) for value in spec.data.get("x_values", [])]
            series = list(spec.data.get("series", []))
            if not x_values or not series:
                raise ValueError("bar_chart requires x_values and series")

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
            ax.set_xlabel(spec.data.get("x_label", ""))
            ax.set_ylabel(spec.data.get("y_label", ""))
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
            x_values = spec.data.get("x_values", [])
            series = list(spec.data.get("series", []))
            if not x_values or not series:
                raise ValueError("line_graph requires x_values and series")

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
            ax.set_xlabel(spec.data.get("x_label", ""))
            ax.set_ylabel(spec.data.get("y_label", ""))
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
            series = list(spec.data.get("series", []))
            if not series:
                raise ValueError("scatter_plot requires series")
            for index, item in enumerate(series):
                x_values = item.get("x_values", spec.data.get("x_values", []))
                y_values = item.get("values", item.get("y_values", []))
                ax.scatter(
                    x_values,
                    y_values,
                    marker=markers[index % len(markers)],
                    label=item.get("name") or f"Series {index + 1}",
                    color=item.get("color"),
                )
            ax.set_xlabel(spec.data.get("x_label", ""))
            ax.set_ylabel(spec.data.get("y_label", ""))
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
            matrix = spec.data.get("matrix", [])
            labels = spec.data.get("labels", [])
            if not matrix:
                raise ValueError("confusion_matrix requires matrix")
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
            labels = spec.data.get("labels", [])
            values = spec.data.get("values", [])
            if not labels or not values:
                series = list(spec.data.get("series", []))
                if series:
                    labels = [item.get("name", f"Slice {index + 1}") for index, item in enumerate(series)]
                    values = [item.get("value", 0) for item in series]
            if not labels or not values:
                raise ValueError("pie_chart requires labels and values")
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
            matrix = spec.data.get("matrix", [])
            labels = spec.data.get("labels", [])
            if not matrix:
                raise ValueError("heatmap requires matrix")
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
            headers = [str(item) for item in spec.data.get("headers", [])]
            rows = self._normalize_table_rows(spec.data.get("rows", []), column_count=len(headers))
            if not headers:
                raise ValueError("table requires headers")
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

            dot = Digraph(comment=spec.title)
            dot.attr(rankdir="TB", size="3.5,4", dpi="300")
            dot.attr("node", fontname="Helvetica", fontsize="9")
            shape_map = {"box": "box", "diamond": "diamond", "oval": "ellipse"}
            for node in spec.data.get("nodes", []):
                dot.node(
                    str(node.get("id")),
                    str(node.get("label", "")),
                    shape=shape_map.get(str(node.get("shape", "box")), "box"),
                )
            for edge in spec.data.get("edges", []):
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
            nodes = list(spec.data.get("nodes", []))
            edges = list(spec.data.get("edges", []))
            if not nodes:
                raise ValueError("flowchart requires nodes")

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
            components = list(spec.data.get("components", []))
            connections = list(spec.data.get("connections", []))
            if not components:
                raise ValueError("architecture_diagram requires components")

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
