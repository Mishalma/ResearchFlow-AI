from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from models.generation import GeneratedPaper, GenerationMetadata
from models.validation import ValidationReport

WorkflowJobStatus = Literal[
    "CREATED",
    "GENERATION_REQUESTED",
    "GENERATING",
    "GENERATED",
    "VALIDATION_REQUESTED",
    "VALIDATING",
    "FIX_REQUESTED",
    "FIXING",
    "FINALIZING",
    "DONE",
    "FAILED",
]

WorkflowJobStage = Literal["job", "generation", "validation", "fix", "finalize", "done", "failed"]
WorkflowValidationMode = Literal["none", "ai_check", "final_report"]
WorkflowConfidenceBand = Literal["unknown", "low", "medium", "high"]
WorkflowRoutingDecision = Literal["pending", "accepted", "flagged"]
WorkflowFinalDisposition = Literal["accepted", "accepted_after_fix", "flagged", "failed"]
WorkflowBoundary = Literal["legacy_full_pipeline", "formatting_complete"]


def _timestamp() -> datetime:
    return datetime.now(UTC)


class WorkflowJobConfig(BaseModel):
    validation_depth: Literal["standard"] = "standard"
    enable_fix_loop: bool = True
    max_iterations: int = Field(default=3, ge=1, le=3)


class WorkflowArtifactPointer(BaseModel):
    uri: str
    owner_service: Literal[
        "upload",
        "generation-service",
        "validation-service",
        "fix-service",
        "finalize-service",
        "phase1-monolith",
    ]
    version: str
    content_type: str
    created_at: datetime = Field(default_factory=_timestamp)
    checksum_sha256: str | None = None


class WorkflowArtifacts(BaseModel):
    raw_upload: WorkflowArtifactPointer | None = None
    extracted_text: WorkflowArtifactPointer | None = None
    draft_v1: WorkflowArtifactPointer | None = None
    draft_v2: WorkflowArtifactPointer | None = None
    draft_v3: WorkflowArtifactPointer | None = None
    draft_v4: WorkflowArtifactPointer | None = None
    draft_v5: WorkflowArtifactPointer | None = None
    final_report: WorkflowArtifactPointer | None = None
    final_accepted_draft: WorkflowArtifactPointer | None = None


class WorkflowScores(BaseModel):
    ai_score: float | None = Field(default=None, ge=0, le=1)
    plagiarism_score: float | None = Field(default=None, ge=0, le=100)
    confidence_band: WorkflowConfidenceBand = "unknown"
    routing_decision: WorkflowRoutingDecision = "pending"


class FixSummary(BaseModel):
    attempted: bool = False
    status: Literal["not_needed", "applied", "failed", "no_change"] = "not_needed"
    iterations: int = Field(default=0, ge=0, le=3)
    changed_sections: list[str] = Field(default_factory=list)
    rewriter_mode: str | None = None
    fallback_reason: str | None = None


class WorkflowActiveTask(BaseModel):
    task_id: str
    queue_name: str
    worker_target: str
    attempt: int = Field(ge=1, default=1)


class WorkflowErrorPayload(BaseModel):
    stage: str
    code: str
    message: str
    retryable: bool
    attempt: int | None = Field(default=None, ge=1)


class WorkflowTimestamps(BaseModel):
    created_at: datetime = Field(default_factory=_timestamp)
    updated_at: datetime = Field(default_factory=_timestamp)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobRecord(BaseModel):
    schema_version: str = "1.0.0"
    job_id: str
    project_id: str
    user_id: str
    request_id: str | None = None
    status: WorkflowJobStatus = "CREATED"
    stage: WorkflowJobStage = "job"
    validation_mode: WorkflowValidationMode = "none"
    enable_fix_loop: bool = True
    iteration: int = Field(default=0, ge=0, le=3)
    max_iterations: int = Field(default=3, ge=1, le=3)
    idempotency_key: str = Field(min_length=8)
    current_draft_uri: str | None = None
    artifacts: WorkflowArtifacts = Field(default_factory=WorkflowArtifacts)
    scores: WorkflowScores = Field(default_factory=WorkflowScores)
    active_task: WorkflowActiveTask | None = None
    error: WorkflowErrorPayload | None = None
    timestamps: WorkflowTimestamps = Field(default_factory=WorkflowTimestamps)


class CreateJobRequest(BaseModel):
    project_id: str = Field(min_length=1)
    config: WorkflowJobConfig = Field(default_factory=WorkflowJobConfig)


class CreateJobResponse(BaseModel):
    job_id: str
    status: WorkflowJobStatus
    stage: WorkflowJobStage
    poll_url: str
    result_url: str


class JobProgress(BaseModel):
    current_step: Literal[
        "queued",
        "generation",
        "validation",
        "fixing",
        "finalizing",
        "complete",
        "failed",
    ]
    percent: int = Field(ge=0, le=100)


class JobStatusResponse(BaseModel):
    job_id: str
    project_id: str
    status: WorkflowJobStatus
    stage: WorkflowJobStage
    validation_mode: WorkflowValidationMode
    iteration: int = Field(ge=0, le=3)
    progress: JobProgress
    current_draft_uri: str | None = None
    scores: WorkflowScores
    error: WorkflowErrorPayload | None = None


class JobResultArtifacts(BaseModel):
    raw_upload_uri: str | None = None
    extracted_text_uri: str | None = None
    draft_v1_uri: str | None = None
    draft_v2_uri: str | None = None
    draft_v3_uri: str | None = None
    draft_v4_uri: str | None = None
    draft_v5_uri: str | None = None
    final_report_uri: str | None = None
    final_accepted_draft_uri: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    project_id: str
    status: Literal["DONE", "FAILED"]
    final_disposition: WorkflowFinalDisposition
    validation_mode: WorkflowValidationMode = "none"
    boundary: WorkflowBoundary | None = None
    editor_url: str | None = None
    generated_paper: GeneratedPaper | None = None
    metadata: GenerationMetadata | None = None
    report: ValidationReport | None = None
    fix_summary: FixSummary | None = None
    artifacts: JobResultArtifacts = Field(default_factory=JobResultArtifacts)
    error: WorkflowErrorPayload | None = None


class GenerationTaskRequest(BaseModel):
    schema_version: str = "1.0.0"
    task_id: str
    job_id: str
    project_id: str
    user_id: str
    attempt: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=8)
    expected_status: WorkflowJobStatus = "GENERATION_REQUESTED"
