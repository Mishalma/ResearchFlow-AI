"""Environment-driven configuration for the humanizer runtime.

This module exposes the requested humanizer tuning constants as module-level
values while also providing a small compatibility wrapper for existing callers
that still expect a ``HumanizerConfig`` object.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_VALID_MODES = {"full", "fast", "lite"}


def _normalize_mode(value: str | None) -> str:
    raw_value = (value or "full").strip().lower() or "full"
    if raw_value not in _VALID_MODES:
        logger.warning(
            "Unknown HUMANIZER_MODE '%s'; falling back to 'full'.",
            raw_value,
        )
        return "full"
    return raw_value


HUMANIZER_MODE = _normalize_mode(os.getenv("HUMANIZER_MODE", "full"))
# "full"  -> Vertex LLM rewrite + perplexity + AI classifier + semantic drift
# "fast"  -> Vertex LLM rewrite only, no perplexity
# "lite"  -> deterministic fallback rewriter only

MAX_ITERATIONS = 5
MAX_TARGET_PARAGRAPHS_PER_SECTION = 8
MIN_BURSTINESS_TO_PASS = 0.45
MAX_AI_PATTERN_SCORE_TO_PASS = 0.55
SEMANTIC_DRIFT_THRESHOLD = 0.15
PERPLEXITY_MIN_HUMAN_SCORE = 35.0
RETRY_ON_DRIFT = True
LOG_MODE_ON_EVERY_RUN = True


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
        logger.warning("Invalid integer for %s=%r; using default %s.", name, value, default)
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using default %s.", name, value, default)
        return default


@dataclass(frozen=True)
class HumanizerConfig:
    """Compatibility wrapper for callers that still expect an object config."""

    mode: str = HUMANIZER_MODE
    max_iterations: int = MAX_ITERATIONS
    max_target_paragraphs_per_section: int = MAX_TARGET_PARAGRAPHS_PER_SECTION
    min_burstiness_to_pass: float = MIN_BURSTINESS_TO_PASS
    max_ai_pattern_score_to_pass: float = MAX_AI_PATTERN_SCORE_TO_PASS
    semantic_drift_threshold: float = SEMANTIC_DRIFT_THRESHOLD
    perplexity_min_human_score: float = PERPLEXITY_MIN_HUMAN_SCORE
    retry_on_drift: bool = RETRY_ON_DRIFT
    log_mode_on_every_run: bool = LOG_MODE_ON_EVERY_RUN
    use_model_rewriter: bool | None = None
    enable_perplexity: bool | None = None
    google_project: str = ""
    google_location: str = "us-central1"
    vertex_model: str = ""
    debug_logging: bool = False

    @property
    def resolved_mode(self) -> str:
        """Return the normalized runtime mode for this config instance."""

        return _normalize_mode(self.mode)

    @property
    def model_rewriter_enabled(self) -> bool:
        """Whether Vertex-backed rewriting should be used."""

        if self.use_model_rewriter is not None:
            return bool(self.use_model_rewriter)
        return self.resolved_mode in {"full", "fast"}

    @property
    def perplexity_enabled(self) -> bool:
        """Whether perplexity scoring should be used."""

        if self.enable_perplexity is not None:
            return bool(self.enable_perplexity)
        return self.resolved_mode == "full"

    @property
    def runtime_mode(self) -> str:
        """Return the effective runtime mode after compatibility overrides."""

        if not self.model_rewriter_enabled:
            return "lite" if not self.perplexity_enabled else "full"
        if not self.perplexity_enabled:
            return "fast"
        return self.resolved_mode

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "HumanizerConfig":
        """Build a compatibility config from shared backend settings and env."""

        resolved_settings = settings or get_settings()
        return cls(
            mode=_normalize_mode(os.getenv("HUMANIZER_MODE", HUMANIZER_MODE)),
            max_iterations=max(1, _get_int("HUMANIZER_MAX_ITERATIONS", MAX_ITERATIONS)),
            max_target_paragraphs_per_section=max(
                1,
                _get_int(
                    "HUMANIZER_MAX_TARGET_PARAGRAPHS_PER_SECTION",
                    MAX_TARGET_PARAGRAPHS_PER_SECTION,
                ),
            ),
            min_burstiness_to_pass=max(
                0.0,
                _get_float("HUMANIZER_MIN_BURSTINESS_TO_PASS", MIN_BURSTINESS_TO_PASS),
            ),
            max_ai_pattern_score_to_pass=max(
                0.0,
                min(
                    1.0,
                    _get_float(
                        "HUMANIZER_MAX_AI_PATTERN_SCORE_TO_PASS",
                        MAX_AI_PATTERN_SCORE_TO_PASS,
                    ),
                ),
            ),
            semantic_drift_threshold=max(
                0.0,
                min(
                    1.0,
                    _get_float(
                        "HUMANIZER_SEMANTIC_DRIFT_THRESHOLD",
                        SEMANTIC_DRIFT_THRESHOLD,
                    ),
                ),
            ),
            perplexity_min_human_score=max(
                1.0,
                _get_float(
                    "HUMANIZER_PERPLEXITY_MIN_HUMAN_SCORE",
                    PERPLEXITY_MIN_HUMAN_SCORE,
                ),
            ),
            retry_on_drift=_get_bool("HUMANIZER_RETRY_ON_DRIFT", RETRY_ON_DRIFT),
            log_mode_on_every_run=_get_bool(
                "HUMANIZER_LOG_MODE_ON_EVERY_RUN",
                LOG_MODE_ON_EVERY_RUN,
            ),
            use_model_rewriter=(
                _get_bool("HUMANIZER_USE_MODEL_REWRITER", True)
                if "HUMANIZER_USE_MODEL_REWRITER" in os.environ
                else None
            ),
            enable_perplexity=(
                _get_bool("HUMANIZER_ENABLE_PERPLEXITY", True)
                if "HUMANIZER_ENABLE_PERPLEXITY" in os.environ
                else None
            ),
            google_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
            or resolved_settings.google_cloud_project,
            google_location=os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
            or resolved_settings.google_cloud_location,
            vertex_model=os.getenv("HUMANIZER_MODEL_NAME", "").strip()
            or resolved_settings.vertex_model
            or "gemini-1.5-pro",
            debug_logging=_get_bool("HUMANIZER_DEBUG_LOGGING", resolved_settings.debug),
        )


__all__ = [
    "HUMANIZER_MODE",
    "MAX_ITERATIONS",
    "MAX_TARGET_PARAGRAPHS_PER_SECTION",
    "MIN_BURSTINESS_TO_PASS",
    "MAX_AI_PATTERN_SCORE_TO_PASS",
    "SEMANTIC_DRIFT_THRESHOLD",
    "PERPLEXITY_MIN_HUMAN_SCORE",
    "RETRY_ON_DRIFT",
    "LOG_MODE_ON_EVERY_RUN",
    "HumanizerConfig",
]
