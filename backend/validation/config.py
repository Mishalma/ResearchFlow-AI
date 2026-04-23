from __future__ import annotations

import os
from dataclasses import dataclass

from core.config import Settings, get_settings


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class ValidationConfig:
    provider_name: str = "internal_fast_validation"
    ai_clean_threshold: float = 0.20
    ai_flag_threshold: float = 0.45
    plagiarism_clean_threshold: float = 5.0
    plagiarism_flag_threshold: float = 10.0
    overlap_ngram_size: int = 5
    overlap_sentence_min_tokens: int = 8
    overlap_ratio_threshold: float = 0.30
    sequence_ratio_threshold: float = 0.82
    perplexity_weight: float = 0.20
    stylometry_weight: float = 0.15
    detector_weight: float = 0.65
    perplexity_model_name: str = "distilgpt2"
    debug_logging: bool = False

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ValidationConfig":
        resolved_settings = settings or get_settings()
        return cls(
            provider_name=os.getenv("VALIDATION_PROVIDER_NAME", "internal_fast_validation").strip()
            or "internal_fast_validation",
            ai_clean_threshold=max(0.0, min(1.0, _get_float("VALIDATION_AI_CLEAN_THRESHOLD", 0.20))),
            ai_flag_threshold=max(0.0, min(1.0, _get_float("VALIDATION_AI_FLAG_THRESHOLD", 0.45))),
            plagiarism_clean_threshold=max(0.0, _get_float("VALIDATION_PLAGIARISM_CLEAN_THRESHOLD", 5.0)),
            plagiarism_flag_threshold=max(0.0, _get_float("VALIDATION_PLAGIARISM_FLAG_THRESHOLD", 10.0)),
            overlap_ngram_size=max(3, _get_int("VALIDATION_OVERLAP_NGRAM_SIZE", 5)),
            overlap_sentence_min_tokens=max(4, _get_int("VALIDATION_OVERLAP_MIN_TOKENS", 8)),
            overlap_ratio_threshold=max(0.05, min(1.0, _get_float("VALIDATION_OVERLAP_RATIO_THRESHOLD", 0.30))),
            sequence_ratio_threshold=max(0.50, min(1.0, _get_float("VALIDATION_SEQUENCE_RATIO_THRESHOLD", 0.82))),
            perplexity_weight=max(0.0, min(1.0, _get_float("VALIDATION_PERPLEXITY_WEIGHT", 0.20))),
            stylometry_weight=max(0.0, min(1.0, _get_float("VALIDATION_STYLOMETRY_WEIGHT", 0.15))),
            detector_weight=max(0.0, min(1.0, _get_float("VALIDATION_DETECTOR_WEIGHT", 0.65))),
            perplexity_model_name=os.getenv("VALIDATION_PERPLEXITY_MODEL_NAME", "distilgpt2").strip()
            or "distilgpt2",
            debug_logging=resolved_settings.debug,
        )
