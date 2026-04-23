from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

PersistenceBackend = Literal["local", "gcp"]
WorkflowDispatchBackend = Literal["local", "cloud_tasks"]
WorkflowGenerationBackend = Literal["local", "service"]
WorkflowValidationBackend = Literal["local", "service"]


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def _get_allowed_origins() -> tuple[str, ...]:
    raw_value = os.getenv("ALLOWED_ORIGINS")
    if not raw_value:
        return ("http://localhost:3000", "http://127.0.0.1:3000")

    origins = tuple(origin.strip() for origin in raw_value.split(",") if origin.strip())
    return origins or ("http://localhost:3000", "http://127.0.0.1:3000")


def _resolve_optional_path(name: str) -> Path | None:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None

    path = Path(raw_value)
    if not path.is_absolute():
        path = BASE_DIR / path

    return path.resolve()


def _resolve_path(name: str, default: Path) -> Path:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default.resolve()

    path = Path(raw_value)
    if not path.is_absolute():
        path = BASE_DIR / path

    return path.resolve()


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    app_name: str
    debug: bool
    allowed_origins: tuple[str, ...]
    uploads_dir: Path
    static_dir: Path
    figures_dir: Path
    outputs_dir: Path
    templates_dir: Path
    local_projects_dir: Path
    local_jobs_dir: Path
    temp_dir: Path
    persistence_backend: PersistenceBackend
    gcs_bucket_name: str
    firestore_projects_collection: str
    firestore_jobs_collection: str
    agent_specs_path: Path
    max_upload_size_mb: int
    max_upload_size_bytes: int
    max_figure_size_mb: int
    max_figure_size_bytes: int
    google_cloud_project: str
    google_cloud_location: str
    workflow_dispatch_backend: WorkflowDispatchBackend
    workflow_generation_backend: WorkflowGenerationBackend
    workflow_validation_backend: WorkflowValidationBackend
    workflow_cloud_tasks_project: str
    workflow_cloud_tasks_location: str
    workflow_cloud_tasks_queue: str
    workflow_cloud_tasks_target_url: str
    workflow_cloud_tasks_service_account_email: str
    generation_service_base_url: str
    generation_service_audience: str
    generation_service_timeout_seconds: int
    validation_service_base_url: str
    validation_service_audience: str
    validation_service_timeout_seconds: int
    vertex_model: str
    vertex_service_account_file: Path | None
    ai_request_timeout_seconds: int
    ai_source_text_max_chars: int
    ai_temperature: float
    ai_max_output_tokens: int
    agent_retry_attempts: int
    agent_retry_backoff_seconds: float
    citation_result_limit: int
    pdflatex_command: str
    pdflatex_timeout_seconds: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    max_upload_size_mb = _get_int("MAX_UPLOAD_SIZE_MB", 10)
    max_figure_size_mb = _get_int("MAX_FIGURE_SIZE_MB", 10)
    persistence_backend = os.getenv("PERSISTENCE_BACKEND", "local").strip().lower() or "local"
    if persistence_backend not in {"local", "gcp"}:
        persistence_backend = "local"
    workflow_dispatch_backend = (
        os.getenv("WORKFLOW_DISPATCH_BACKEND", "local").strip().lower() or "local"
    )
    if workflow_dispatch_backend not in {"local", "cloud_tasks"}:
        workflow_dispatch_backend = "local"
    workflow_generation_backend = (
        os.getenv("WORKFLOW_GENERATION_BACKEND", "local").strip().lower() or "local"
    )
    if workflow_generation_backend not in {"local", "service"}:
        workflow_generation_backend = "local"
    workflow_validation_backend = (
        os.getenv("WORKFLOW_VALIDATION_BACKEND", "local").strip().lower() or "local"
    )
    if workflow_validation_backend not in {"local", "service"}:
        workflow_validation_backend = "local"
    google_cloud_project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    google_cloud_location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"

    return Settings(
        base_dir=BASE_DIR,
        app_name=os.getenv("APP_NAME", "PaperEasy Backend"),
        debug=_get_bool("DEBUG"),
        allowed_origins=_get_allowed_origins(),
        uploads_dir=BASE_DIR / "uploads",
        static_dir=BASE_DIR / "static",
        figures_dir=BASE_DIR / "static" / "figures",
        outputs_dir=BASE_DIR / "outputs",
        templates_dir=BASE_DIR / "templates",
        local_projects_dir=_resolve_path("LOCAL_PROJECTS_DIR", BASE_DIR / "data" / "projects"),
        local_jobs_dir=_resolve_path("LOCAL_JOBS_DIR", BASE_DIR / "data" / "jobs"),
        temp_dir=_resolve_path("TEMP_DIR", BASE_DIR / ".tmp"),
        persistence_backend=persistence_backend,
        gcs_bucket_name=os.getenv("GCS_BUCKET_NAME", "").strip(),
        firestore_projects_collection=os.getenv("FIRESTORE_PROJECTS_COLLECTION", "papereasy-projects").strip()
        or "papereasy-projects",
        firestore_jobs_collection=os.getenv("FIRESTORE_JOBS_COLLECTION", "papereasy-jobs").strip()
        or "papereasy-jobs",
        agent_specs_path=_resolve_path("AGENT_SPECS_PATH", BASE_DIR / "agents" / "agent_specs.json"),
        max_upload_size_mb=max_upload_size_mb,
        max_upload_size_bytes=max_upload_size_mb * 1024 * 1024,
        max_figure_size_mb=max_figure_size_mb,
        max_figure_size_bytes=max_figure_size_mb * 1024 * 1024,
        google_cloud_project=google_cloud_project,
        google_cloud_location=google_cloud_location,
        workflow_dispatch_backend=workflow_dispatch_backend,
        workflow_generation_backend=workflow_generation_backend,
        workflow_validation_backend=workflow_validation_backend,
        workflow_cloud_tasks_project=(
            os.getenv("WORKFLOW_CLOUD_TASKS_PROJECT", "").strip() or google_cloud_project
        ),
        workflow_cloud_tasks_location=(
            os.getenv("WORKFLOW_CLOUD_TASKS_LOCATION", "").strip() or google_cloud_location
        ),
        workflow_cloud_tasks_queue=(
            os.getenv("WORKFLOW_CLOUD_TASKS_QUEUE", "papereasy-generation").strip()
            or "papereasy-generation"
        ),
        workflow_cloud_tasks_target_url=os.getenv("WORKFLOW_CLOUD_TASKS_TARGET_URL", "").strip(),
        workflow_cloud_tasks_service_account_email=os.getenv(
            "WORKFLOW_CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL", ""
        ).strip(),
        generation_service_base_url=os.getenv("GENERATION_SERVICE_BASE_URL", "").strip(),
        generation_service_audience=os.getenv("GENERATION_SERVICE_AUDIENCE", "").strip(),
        generation_service_timeout_seconds=max(
            30,
            _get_int("GENERATION_SERVICE_TIMEOUT_SECONDS", 1500),
        ),
        validation_service_base_url=os.getenv("VALIDATION_SERVICE_BASE_URL", "").strip(),
        validation_service_audience=os.getenv("VALIDATION_SERVICE_AUDIENCE", "").strip(),
        validation_service_timeout_seconds=max(
            30,
            _get_int("VALIDATION_SERVICE_TIMEOUT_SECONDS", 120),
        ),
        vertex_model=os.getenv("VERTEX_MODEL", "gemini-2.5-flash").strip()
        or "gemini-2.5-flash",
        vertex_service_account_file=_resolve_optional_path("VERTEX_SERVICE_ACCOUNT_FILE"),
        ai_request_timeout_seconds=_get_int("AI_REQUEST_TIMEOUT_SECONDS", 60),
        ai_source_text_max_chars=_get_int("AI_SOURCE_TEXT_MAX_CHARS", 20000),
        ai_temperature=_get_float("AI_TEMPERATURE", 0.0),
        ai_max_output_tokens=_get_int("AI_MAX_OUTPUT_TOKENS", 4096),
        agent_retry_attempts=max(1, _get_int("AGENT_RETRY_ATTEMPTS", 2)),
        agent_retry_backoff_seconds=max(0.0, _get_float("AGENT_RETRY_BACKOFF_SECONDS", 1.0)),
        citation_result_limit=max(1, _get_int("CITATION_RESULT_LIMIT", 3)),
        pdflatex_command=os.getenv("PDFLATEX_COMMAND", "pdflatex").strip() or "pdflatex",
        pdflatex_timeout_seconds=max(10, _get_int("PDFLATEX_TIMEOUT_SECONDS", 60)),
    )

