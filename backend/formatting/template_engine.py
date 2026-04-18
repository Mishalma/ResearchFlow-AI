from __future__ import annotations

from pathlib import Path

from formatting.config import FormattingConfig


def _build_environment(*, template_dir: Path, autoescape: bool):
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html", "xml")) if autoescape else False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    environment.filters["upper_roman"] = _upper_roman
    return environment


def render_latex_document(*, context: dict[str, object], config: FormattingConfig) -> str:
    if config.template_dir is None:
        raise RuntimeError("Formatting template_dir is not configured.")
    environment = _build_environment(template_dir=config.template_dir, autoescape=False)
    template = environment.get_template("ieee_conference.tex.j2")
    return template.render(**context)


def render_html_document(*, context: dict[str, object], config: FormattingConfig) -> str:
    if config.template_dir is None:
        raise RuntimeError("Formatting template_dir is not configured.")
    environment = _build_environment(template_dir=config.template_dir, autoescape=True)
    template = environment.get_template("ieee_preview.html.j2")
    return template.render(**context)


def _upper_roman(value: int) -> str:
    numerals = [
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
    number = int(value)
    if number <= 0:
        return str(value)
    parts: list[str] = []
    for arabic, roman in numerals:
        while number >= arabic:
            parts.append(roman)
            number -= arabic
    return "".join(parts)
