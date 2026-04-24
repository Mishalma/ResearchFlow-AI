from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.config import Settings, get_settings

DetectorBackend = Literal["heuristic", "desklib"]


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


def _get_detector_backend() -> DetectorBackend:
    value = os.getenv("AI_DETECTOR_BACKEND", "heuristic").strip().lower() or "heuristic"
    if value in {"heuristic", "desklib"}:
        return value
    return "heuristic"


def _get_path(name: str, default: str) -> Path:
    value = os.getenv(name, default).strip() or default
    return Path(value).expanduser()


@dataclass(frozen=True)
class ValidationConfig:
    provider_name: str = "internal_fast_validation"
    ai_accept_threshold: float = 0.10
    plagiarism_accept_threshold: float = 10.0
    ai_severe_threshold: float = 0.35
    plagiarism_severe_threshold: float = 20.0
    overlap_ngram_size: int = 5
    overlap_sentence_min_tokens: int = 8
    overlap_ratio_threshold: float = 0.30
    sequence_ratio_threshold: float = 0.82
    perplexity_weight: float = 0.20
    stylometry_weight: float = 0.15
    detector_weight: float = 0.65
    perplexity_model_name: str = "distilgpt2"
    ai_detector_backend: DetectorBackend = "heuristic"
    ai_detector_model_id: str = "desklib/ai-text-detector-academic-v1.01"
    ai_detector_model_gcs_uri: str = ""
    ai_detector_model_path: Path = Path("/tmp/papereasy-models/desklib-ai-text-detector-academic-v1.01")
    ai_detector_max_length: int = 768
    ai_detector_batch_size: int = 8
    ai_detector_device: str = "auto"
    ai_detector_window_stride: int = 128
    debug_logging: bool = False

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ValidationConfig":
        resolved_settings = settings or get_settings()
        return cls(
            provider_name=os.getenv("VALIDATION_PROVIDER_NAME", "internal_fast_validation").strip()
            or "internal_fast_validation",
            ai_accept_threshold=max(0.0, min(1.0, _get_float("VALIDATION_AI_ACCEPT_THRESHOLD", 0.10))),
            plagiarism_accept_threshold=max(
                0.0,
                _get_float("VALIDATION_PLAGIARISM_ACCEPT_THRESHOLD", 10.0),
            ),
            ai_severe_threshold=max(0.0, min(1.0, _get_float("VALIDATION_AI_SEVERE_THRESHOLD", 0.35))),
            plagiarism_severe_threshold=max(
                0.0,
                _get_float("VALIDATION_PLAGIARISM_SEVERE_THRESHOLD", 20.0),
            ),
            overlap_ngram_size=max(3, _get_int("VALIDATION_OVERLAP_NGRAM_SIZE", 5)),
            overlap_sentence_min_tokens=max(4, _get_int("VALIDATION_OVERLAP_MIN_TOKENS", 8)),
            overlap_ratio_threshold=max(0.05, min(1.0, _get_float("VALIDATION_OVERLAP_RATIO_THRESHOLD", 0.30))),
            sequence_ratio_threshold=max(0.50, min(1.0, _get_float("VALIDATION_SEQUENCE_RATIO_THRESHOLD", 0.82))),
            perplexity_weight=max(0.0, min(1.0, _get_float("VALIDATION_PERPLEXITY_WEIGHT", 0.20))),
            stylometry_weight=max(0.0, min(1.0, _get_float("VALIDATION_STYLOMETRY_WEIGHT", 0.15))),
            detector_weight=max(0.0, min(1.0, _get_float("VALIDATION_DETECTOR_WEIGHT", 0.65))),
            perplexity_model_name=os.getenv("VALIDATION_PERPLEXITY_MODEL_NAME", "distilgpt2").strip()
            or "distilgpt2",
            ai_detector_backend=_get_detector_backend(),
            ai_detector_model_id=os.getenv(
                "AI_DETECTOR_MODEL_ID",
                "desklib/ai-text-detector-academic-v1.01",
            ).strip()
            or "desklib/ai-text-detector-academic-v1.01",
            ai_detector_model_gcs_uri=os.getenv("AI_DETECTOR_MODEL_GCS_URI", "").strip(),
            ai_detector_model_path=_get_path(
                "AI_DETECTOR_MODEL_PATH",
                "/tmp/papereasy-models/desklib-ai-text-detector-academic-v1.01",
            ),
            ai_detector_max_length=max(128, _get_int("AI_DETECTOR_MAX_LENGTH", 768)),
            ai_detector_batch_size=max(1, _get_int("AI_DETECTOR_BATCH_SIZE", 8)),
            ai_detector_device=os.getenv("AI_DETECTOR_DEVICE", "auto").strip().lower() or "auto",
            ai_detector_window_stride=max(0, _get_int("AI_DETECTOR_WINDOW_STRIDE", 128)),
            debug_logging=resolved_settings.debug,
        )
