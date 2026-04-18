from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

from formatting.config import FormattingConfig
from formatting.schemas import CompileReport, CompilerDiagnostic, FormattedPaper, FormattingArtifacts, FormattingProfile
from formatting.utils import copy_support_assets
from formatting.validators import compile_retry_recommended, parse_latex_diagnostics


def compile_latex_document(
    *,
    latex_source: str,
    html_preview: str,
    profile: FormattingProfile,
    config: FormattingConfig,
    work_dir: Path,
) -> FormattedPaper:
    work_dir.mkdir(parents=True, exist_ok=True)
    copy_support_assets(config=config, work_dir=work_dir)

    tex_path = work_dir / config.latex_file_name
    tex_path.write_text(latex_source, encoding="utf-8")

    diagnostics: list[CompilerDiagnostic] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    return_code: int | None = None

    pdflatex_binary = which(config.pdflatex_command)
    if pdflatex_binary is None:
        diagnostics.append(
            CompilerDiagnostic(
                severity="error",
                category="missing_dependency",
                message="pdflatex is not installed or not available on PATH.",
                retryable=False,
                remediation_target="formatting",
            )
        )
        artifacts = FormattingArtifacts(
            work_dir=str(work_dir),
            tex_path=str(tex_path),
            html_preview_path=str(work_dir / config.html_preview_file_name),
        )
        compile_report = CompileReport(
            success=False,
            return_code=None,
            diagnostics=diagnostics,
            retry_recommended=False,
        )
        return FormattedPaper(
            profile=profile,
            latex_source=latex_source,
            html_preview=html_preview,
            artifacts=artifacts,
            compile_report=compile_report,
            metadata={"compile_passes_attempted": 0},
        )

    command = [
        pdflatex_binary,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        tex_path.name,
    ]
    for _pass in range(config.compile_passes):
        try:
            process = subprocess.run(
                command,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=config.compiler_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="error",
                    category="compile_timeout",
                    message="pdflatex timed out while compiling the IEEE manuscript.",
                    retryable=True,
                    remediation_target="formatting",
                )
            )
            stdout_parts.append((exc.stdout or ""))
            stderr_parts.append((exc.stderr or ""))
            return_code = None
            break

        stdout_parts.append(process.stdout or "")
        stderr_parts.append(process.stderr or "")
        return_code = process.returncode
        if process.returncode != 0:
            break

    pdf_path = tex_path.with_suffix(".pdf")
    log_path = tex_path.with_suffix(".log")
    aux_path = tex_path.with_suffix(".aux")
    bbl_path = tex_path.with_suffix(".bbl")

    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    diagnostics.extend(
        parse_latex_diagnostics(
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            log_text=log_text,
        )
    )

    success = bool(return_code == 0 and pdf_path.exists())
    if not success and not diagnostics:
        diagnostics.append(
            CompilerDiagnostic(
                severity="error",
                category="compile_failure",
                message="pdflatex failed to produce a PDF output.",
                retryable=True,
                remediation_target="formatting",
            )
        )

    stdout_tail = _tail_text("\n".join(stdout_parts), limit_lines=config.diagnostic_excerpt_lines)
    stderr_tail = _tail_text("\n".join(stderr_parts), limit_lines=config.diagnostic_excerpt_lines)
    log_excerpt = _tail_text(log_text, limit_lines=config.diagnostic_excerpt_lines)

    artifacts = FormattingArtifacts(
        work_dir=str(work_dir),
        tex_path=str(tex_path),
        pdf_path=str(pdf_path) if pdf_path.exists() else None,
        html_preview_path=str(work_dir / config.html_preview_file_name),
        bbl_path=str(bbl_path) if bbl_path.exists() else None,
        aux_path=str(aux_path) if aux_path.exists() else None,
        log_path=str(log_path) if log_path.exists() else None,
    )
    compile_report = CompileReport(
        success=success,
        return_code=return_code,
        diagnostics=diagnostics,
        stdout_tail=stdout_tail or None,
        stderr_tail=stderr_tail or None,
        log_excerpt=log_excerpt or None,
        retry_recommended=compile_retry_recommended(diagnostics),
    )
    return FormattedPaper(
        profile=profile,
        latex_source=latex_source,
        html_preview=html_preview,
        artifacts=artifacts,
        compile_report=compile_report,
        metadata={"compile_passes_attempted": config.compile_passes},
    )


def _tail_text(value: str, *, limit_lines: int) -> str:
    lines = [line.rstrip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-limit_lines:])
