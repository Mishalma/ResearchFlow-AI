from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from models.generation import GeneratedPaper


class FormattingProfile(BaseModel):
    profile_name: str
    paper_size: str
    top_margin_mm: float
    bottom_margin_mm: float
    left_margin_mm: float
    right_margin_mm: float
    column_gap_mm: float
    column_width_mm: float
    body_font_pt: float
    title_font_pt: float
    author_font_pt: float
    affiliation_font_pt: float
    email_font_pt: float
    paragraph_indent_mm: float
    two_column: bool = True
    sort_index_terms: bool = True


class CompilerDiagnostic(BaseModel):
    severity: str
    category: str
    message: str
    line: int | None = None
    file: str | None = None
    retryable: bool = False
    remediation_target: str | None = None

    @model_validator(mode="after")
    def normalize(self) -> "CompilerDiagnostic":
        self.severity = self.severity.strip()
        self.category = self.category.strip()
        self.message = self.message.strip()
        if self.file is not None:
            cleaned = self.file.strip()
            self.file = cleaned or None
        if self.remediation_target is not None:
            cleaned = self.remediation_target.strip()
            self.remediation_target = cleaned or None
        return self


class CompileReport(BaseModel):
    success: bool
    return_code: int | None = None
    diagnostics: list[CompilerDiagnostic] = Field(default_factory=list)
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    log_excerpt: str | None = None
    retry_recommended: bool = False


class FormattingArtifacts(BaseModel):
    work_dir: str | None = None
    tex_path: str | None = None
    pdf_path: str | None = None
    html_preview_path: str | None = None
    bbl_path: str | None = None
    aux_path: str | None = None
    log_path: str | None = None


class FormattedPaper(BaseModel):
    profile: FormattingProfile
    latex_source: str
    html_preview: str
    artifacts: FormattingArtifacts
    compile_report: CompileReport
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormattingAgentError(BaseModel):
    code: str
    message: str
    trace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class FormattingAgentResult(BaseModel):
    formatted_paper: FormattedPaper | None = None
    paper_snapshot: GeneratedPaper | None = None
    error: FormattingAgentError | None = None
    trace_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "FormattingAgentResult":
        if self.formatted_paper is None and self.error is None:
            raise ValueError("result must include a formatted_paper or an error")
        return self
