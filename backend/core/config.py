from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


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


@dataclass(frozen=True)
class Settings:
    app_name: str
    debug: bool
    allowed_origins: tuple[str, ...]
    uploads_dir: Path
    static_dir: Path
    figures_dir: Path
    outputs_dir: Path
    templates_dir: Path
    max_upload_size_mb: int
    max_upload_size_bytes: int
    max_figure_size_mb: int
    max_figure_size_bytes: int
    google_cloud_project: str
    google_cloud_location: str
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

    return Settings(
        app_name=os.getenv("APP_NAME", "PaperEasy Backend"),
        debug=_get_bool("DEBUG"),
        allowed_origins=_get_allowed_origins(),
        uploads_dir=BASE_DIR / "uploads",
        static_dir=BASE_DIR / "static",
        figures_dir=BASE_DIR / "static" / "figures",
        outputs_dir=BASE_DIR / "outputs",
        templates_dir=BASE_DIR / "templates",
        max_upload_size_mb=max_upload_size_mb,
        max_upload_size_bytes=max_upload_size_mb * 1024 * 1024,
        max_figure_size_mb=max_figure_size_mb,
        max_figure_size_bytes=max_figure_size_mb * 1024 * 1024,
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
        or "us-central1",
        vertex_model=os.getenv("VERTEX_MODEL", "gemini-2.5-flash").strip()
        or "gemini-2.5-flash",
        vertex_service_account_file=_resolve_optional_path("VERTEX_SERVICE_ACCOUNT_FILE"),
        ai_request_timeout_seconds=_get_int("AI_REQUEST_TIMEOUT_SECONDS", 60),
        ai_source_text_max_chars=_get_int("AI_SOURCE_TEXT_MAX_CHARS", 20000),
        ai_temperature=_get_float("AI_TEMPERATURE", 0.2),
        ai_max_output_tokens=_get_int("AI_MAX_OUTPUT_TOKENS", 2000),
        agent_retry_attempts=max(1, _get_int("AGENT_RETRY_ATTEMPTS", 2)),
        agent_retry_backoff_seconds=max(0.0, _get_float("AGENT_RETRY_BACKOFF_SECONDS", 1.0)),
        citation_result_limit=max(1, _get_int("CITATION_RESULT_LIMIT", 3)),
        pdflatex_command=os.getenv("PDFLATEX_COMMAND", "pdflatex").strip() or "pdflatex",
        pdflatex_timeout_seconds=max(10, _get_int("PDFLATEX_TIMEOUT_SECONDS", 60)),
    )
