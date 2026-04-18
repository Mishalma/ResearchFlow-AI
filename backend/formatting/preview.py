from __future__ import annotations

from pathlib import Path

from formatting.config import FormattingConfig
from formatting.template_engine import render_html_document


def generate_html_preview(
    *,
    context: dict[str, object],
    config: FormattingConfig,
    work_dir: Path,
) -> tuple[str, Path]:
    html_preview = render_html_document(context=context, config=config)
    output_path = work_dir / config.html_preview_file_name
    output_path.write_text(html_preview, encoding="utf-8")
    return html_preview, output_path
