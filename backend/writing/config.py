from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.config import Settings, get_settings
from writing.schemas import BODY_WRITING_SECTIONS


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


@dataclass(frozen=True)
class WritingConfig:
    use_model_generator: bool = True
    enable_diversity_pass: bool = True
    debug_logging: bool = False
    sentence_annotation_mode: str = "heuristic"
    preferred_title_max_words: int = 14
    diversity_backend: str = "deterministic"
    reducer_model: str | None = None
    low_confidence_threshold: float = 0.4
    medium_confidence_threshold: float = 0.65
    high_confidence_threshold: float = 0.85
    section_sentence_limits: dict[str, int] = field(
        default_factory=lambda: {
            "abstract": 4,
            **{section_name: 5 for section_name in BODY_WRITING_SECTIONS},
        }
    )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "WritingConfig":
        resolved_settings = settings or get_settings()
        return cls(
            use_model_generator=_get_bool("WRITING_USE_MODEL_GENERATOR", True),
            enable_diversity_pass=_get_bool("WRITING_ENABLE_DIVERSITY_PASS", True),
            debug_logging=_get_bool("WRITING_DEBUG_LOGGING", False),
            sentence_annotation_mode=os.getenv("WRITING_SENTENCE_ANNOTATION_MODE", "heuristic").strip() or "heuristic",
            preferred_title_max_words=max(6, _get_int("WRITING_PREFERRED_TITLE_MAX_WORDS", 14)),
            diversity_backend=os.getenv("WRITING_DIVERSITY_BACKEND", "deterministic").strip() or "deterministic",
            reducer_model=os.getenv("WRITING_MODEL_NAME", "").strip() or resolved_settings.vertex_model,
        )
