from __future__ import annotations

import re

from formatting.schemas import CompilerDiagnostic

LINE_NUMBER_PATTERN = re.compile(r"l\.(\d+)")
OVERFULL_PATTERN = re.compile(r"Overfull \\hbox .* at lines? (\d+)(?:--(\d+))?")
UNDERFULL_PATTERN = re.compile(r"Underfull \\hbox .* at lines? (\d+)(?:--(\d+))?")
UNDEFINED_CITATION_PATTERN = re.compile(r"Citation [`']([^`']+)[`'] .* undefined", re.IGNORECASE)
UNDEFINED_REFERENCE_PATTERN = re.compile(r"Reference [`']([^`']+)[`'] .* undefined", re.IGNORECASE)
DUPLICATE_LABEL_PATTERN = re.compile(r"Label [`']([^`']+)[`'] multiply defined", re.IGNORECASE)
MISSING_PACKAGE_PATTERN = re.compile(r"LaTeX Error: File [`']([^`']+)[`'] not found", re.IGNORECASE)
MISSING_FILE_PATTERN = re.compile(r"LaTeX Warning: File [`']([^`']+)[`'] not found", re.IGNORECASE)
BEGIN_END_PATTERN = re.compile(r"LaTeX Error: \\begin\{([^}]+)\} .* ended by \\end\{([^}]+)\}", re.IGNORECASE)


def parse_latex_diagnostics(
    *,
    stdout: str,
    stderr: str,
    log_text: str,
) -> list[CompilerDiagnostic]:
    lines = _combined_lines(stdout=stdout, stderr=stderr, log_text=log_text)
    diagnostics: list[CompilerDiagnostic] = []
    last_error_line: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        line_number_match = LINE_NUMBER_PATTERN.search(stripped)
        if line_number_match:
            last_error_line = int(line_number_match.group(1))

        if stripped.startswith("! Undefined control sequence."):
            diagnostics.append(
                CompilerDiagnostic(
                    severity="error",
                    category="undefined_control_sequence",
                    message="Undefined LaTeX control sequence detected during compilation.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="formatting",
                )
            )
        elif stripped.startswith("! Missing $ inserted."):
            diagnostics.append(
                CompilerDiagnostic(
                    severity="error",
                    category="invalid_math_environment",
                    message="LaTeX detected an invalid math environment or unescaped math token.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="upstream_content",
                )
            )
        elif stripped.startswith("! Extra }, or forgotten \\endgroup."):
            diagnostics.append(
                CompilerDiagnostic(
                    severity="error",
                    category="unbalanced_braces",
                    message="The rendered LaTeX contains unbalanced braces or grouping.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="formatting",
                )
            )
        elif "LaTeX Error:" in stripped:
            diagnostics.append(_map_latex_error_line(stripped, last_error_line))

        overfull_match = OVERFULL_PATTERN.search(stripped)
        if overfull_match:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    category="overfull_hbox",
                    message=stripped,
                    line=int(overfull_match.group(1)),
                    retryable=True,
                    remediation_target="formatting",
                )
            )

        underfull_match = UNDERFULL_PATTERN.search(stripped)
        if underfull_match:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    category="underfull_hbox",
                    message=stripped,
                    line=int(underfull_match.group(1)),
                    retryable=False,
                    remediation_target="formatting",
                )
            )

        citation_match = UNDEFINED_CITATION_PATTERN.search(stripped)
        if citation_match:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="error",
                    category="undefined_citation",
                    message=f"Undefined citation '{citation_match.group(1)}' was reported by LaTeX.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="citation",
                )
            )

        reference_match = UNDEFINED_REFERENCE_PATTERN.search(stripped)
        if reference_match:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    category="undefined_reference",
                    message=f"Undefined reference '{reference_match.group(1)}' was reported by LaTeX.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="formatting",
                )
            )

        duplicate_label_match = DUPLICATE_LABEL_PATTERN.search(stripped)
        if duplicate_label_match:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    category="duplicate_label",
                    message=f"Duplicate LaTeX label '{duplicate_label_match.group(1)}' was detected.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="formatting",
                )
            )

        missing_file_match = MISSING_FILE_PATTERN.search(stripped)
        if missing_file_match:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="error",
                    category="missing_asset",
                    message=f"Missing figure or asset file '{missing_file_match.group(1)}'.",
                    line=last_error_line,
                    retryable=True,
                    remediation_target="assets",
                )
            )

    return _deduplicate_diagnostics(diagnostics)


def compile_retry_recommended(diagnostics: list[CompilerDiagnostic]) -> bool:
    return any(diagnostic.retryable for diagnostic in diagnostics)


def _map_latex_error_line(line: str, line_number: int | None) -> CompilerDiagnostic:
    missing_package_match = MISSING_PACKAGE_PATTERN.search(line)
    if missing_package_match:
        return CompilerDiagnostic(
            severity="error",
            category="missing_package",
            message=f"Required LaTeX package or class '{missing_package_match.group(1)}' is not available.",
            line=line_number,
            retryable=False,
            remediation_target="formatting",
        )
    begin_end_match = BEGIN_END_PATTERN.search(line)
    if begin_end_match:
        left, right = begin_end_match.groups()
        category = "malformed_table_environment" if {"table", "tabular"} & {left, right} else "invalid_environment"
        target = "upstream_content" if "equation" in {left, right} else "formatting"
        return CompilerDiagnostic(
            severity="error",
            category=category,
            message=line,
            line=line_number,
            retryable=True,
            remediation_target=target,
        )
    return CompilerDiagnostic(
        severity="error",
        category="latex_error",
        message=line,
        line=line_number,
        retryable=True,
        remediation_target="formatting",
    )


def _combined_lines(*, stdout: str, stderr: str, log_text: str) -> list[str]:
    combined = "\n".join(part for part in [stdout, stderr, log_text] if part)
    return combined.splitlines()


def _deduplicate_diagnostics(diagnostics: list[CompilerDiagnostic]) -> list[CompilerDiagnostic]:
    seen: set[tuple[str, str, str, int | None]] = set()
    unique: list[CompilerDiagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.severity, diagnostic.category, diagnostic.message, diagnostic.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return unique
