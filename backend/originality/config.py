from __future__ import annotations

import os
from dataclasses import dataclass

from core.config import Settings, get_settings


def _get_bool(name: str, default: bool) -> bool:
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


@dataclass(frozen=True)
class OriginalityConfig:
    primary_provider: str = "winston_ai"
    fallback_provider: str = "copyleaks"
    http_timeout_seconds: int = 30
    retry_attempts: int = 2
    retry_backoff_seconds: float = 1.0
    section_chunk_chars: int = 8000
    section_chunk_overlap_chars: int = 600
    provider_failure_retry_attempts: int = 1
    winston_base_url: str = "https://api.gowinston.ai"
    winston_plagiarism_path: str = "/v2/plagiarism"
    winston_api_key: str | None = None
    winston_language: str = "en"
    winston_country: str = "us"
    copyleaks_id_base_url: str = "https://id.copyleaks.com"
    copyleaks_api_base_url: str = "https://api.copyleaks.com"
    copyleaks_email: str | None = None
    copyleaks_api_key: str | None = None
    copyleaks_callback_base_url: str | None = None
    copyleaks_wait_timeout_seconds: int = 45
    copyleaks_poll_interval_seconds: float = 1.0
    copyleaks_sandbox: bool = False
    common_phrase_max_chars: int = 72
    quoted_citation_window_chars: int = 140
    blocking_severity_threshold: float = 0.8
    manual_review_severity_threshold: float = 0.55
    retry_humanizer_ai_threshold: float = 0.45
    debug_logging: bool = False

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "OriginalityConfig":
        resolved_settings = settings or get_settings()
        return cls(
            primary_provider=os.getenv("ORIGINALITY_PRIMARY_PROVIDER", "winston_ai").strip() or "winston_ai",
            fallback_provider=os.getenv("ORIGINALITY_FALLBACK_PROVIDER", "copyleaks").strip() or "copyleaks",
            http_timeout_seconds=max(5, _get_int("ORIGINALITY_HTTP_TIMEOUT_SECONDS", 30)),
            retry_attempts=max(1, _get_int("ORIGINALITY_HTTP_RETRY_ATTEMPTS", 2)),
            retry_backoff_seconds=max(0.0, _get_float("ORIGINALITY_HTTP_RETRY_BACKOFF_SECONDS", 1.0)),
            section_chunk_chars=max(1000, _get_int("ORIGINALITY_SECTION_CHUNK_CHARS", 8000)),
            section_chunk_overlap_chars=max(0, _get_int("ORIGINALITY_SECTION_CHUNK_OVERLAP_CHARS", 600)),
            provider_failure_retry_attempts=max(0, _get_int("ORIGINALITY_PROVIDER_FAILURE_RETRIES", 1)),
            winston_base_url=os.getenv("WINSTON_BASE_URL", "https://api.gowinston.ai").strip() or "https://api.gowinston.ai",
            winston_plagiarism_path=os.getenv("WINSTON_PLAGIARISM_PATH", "/v2/plagiarism").strip() or "/v2/plagiarism",
            winston_api_key=os.getenv("WINSTON_API_KEY", "").strip() or None,
            winston_language=os.getenv("WINSTON_LANGUAGE", "en").strip() or "en",
            winston_country=os.getenv("WINSTON_COUNTRY", "us").strip() or "us",
            copyleaks_id_base_url=os.getenv("COPYLEAKS_ID_BASE_URL", "https://id.copyleaks.com").strip() or "https://id.copyleaks.com",
            copyleaks_api_base_url=os.getenv("COPYLEAKS_API_BASE_URL", "https://api.copyleaks.com").strip() or "https://api.copyleaks.com",
            copyleaks_email=os.getenv("COPYLEAKS_EMAIL", "").strip() or None,
            copyleaks_api_key=os.getenv("COPYLEAKS_API_KEY", "").strip() or None,
            copyleaks_callback_base_url=os.getenv("COPYLEAKS_CALLBACK_BASE_URL", "").strip() or None,
            copyleaks_wait_timeout_seconds=max(10, _get_int("COPYLEAKS_WAIT_TIMEOUT_SECONDS", 45)),
            copyleaks_poll_interval_seconds=max(0.2, _get_float("COPYLEAKS_POLL_INTERVAL_SECONDS", 1.0)),
            copyleaks_sandbox=_get_bool("COPYLEAKS_SANDBOX", False),
            common_phrase_max_chars=max(20, _get_int("ORIGINALITY_COMMON_PHRASE_MAX_CHARS", 72)),
            quoted_citation_window_chars=max(20, _get_int("ORIGINALITY_QUOTED_CITATION_WINDOW_CHARS", 140)),
            blocking_severity_threshold=max(0.1, min(1.0, _get_float("ORIGINALITY_BLOCKING_SEVERITY_THRESHOLD", 0.8))),
            manual_review_severity_threshold=max(0.1, min(1.0, _get_float("ORIGINALITY_MANUAL_REVIEW_SEVERITY_THRESHOLD", 0.55))),
            retry_humanizer_ai_threshold=max(0.1, min(1.0, _get_float("ORIGINALITY_RETRY_HUMANIZER_AI_THRESHOLD", 0.45))),
            debug_logging=_get_bool("ORIGINALITY_DEBUG_LOGGING", resolved_settings.debug),
        )
