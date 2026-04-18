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
class HumanizerConfig:
    use_model_rewriter: bool = True
    enable_perplexity: bool = True
    debug_logging: bool = False
    max_iterations: int = 2
    max_target_paragraphs_per_section: int = 2
    min_section_improvement: float = 0.03
    ai_pattern_threshold: float = 0.42
    writer_loopback_threshold: float = 0.72
    semantic_similarity_threshold: float = 0.72
    perplexity_model_name: str = "distilgpt2"
    perplexity_chunk_tokens: int = 512
    perplexity_stride_tokens: int = 256
    perplexity_low_threshold: float = 15.0
    perplexity_high_threshold: float = 120.0
    spacy_model_name: str = "en_core_web_sm"
    rewriter_model: str | None = None
    model_local_files_only: bool = False
    preserve_first_person_in_discussion: bool = True

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "HumanizerConfig":
        resolved_settings = settings or get_settings()
        return cls(
            use_model_rewriter=_get_bool("HUMANIZER_USE_MODEL_REWRITER", True),
            enable_perplexity=_get_bool("HUMANIZER_ENABLE_PERPLEXITY", True),
            debug_logging=_get_bool("HUMANIZER_DEBUG_LOGGING", resolved_settings.debug),
            max_iterations=max(1, _get_int("HUMANIZER_MAX_ITERATIONS", 2)),
            max_target_paragraphs_per_section=max(
                1,
                _get_int("HUMANIZER_MAX_TARGET_PARAGRAPHS_PER_SECTION", 2),
            ),
            min_section_improvement=max(
                0.0,
                _get_float("HUMANIZER_MIN_SECTION_IMPROVEMENT", 0.03),
            ),
            ai_pattern_threshold=max(
                0.0,
                min(1.0, _get_float("HUMANIZER_AI_PATTERN_THRESHOLD", 0.42)),
            ),
            writer_loopback_threshold=max(
                0.0,
                min(1.0, _get_float("HUMANIZER_WRITER_LOOPBACK_THRESHOLD", 0.72)),
            ),
            semantic_similarity_threshold=max(
                0.0,
                min(1.0, _get_float("HUMANIZER_SEMANTIC_SIMILARITY_THRESHOLD", 0.72)),
            ),
            perplexity_model_name=os.getenv("HUMANIZER_PERPLEXITY_MODEL_NAME", "distilgpt2").strip() or "distilgpt2",
            perplexity_chunk_tokens=max(64, _get_int("HUMANIZER_PERPLEXITY_CHUNK_TOKENS", 512)),
            perplexity_stride_tokens=max(32, _get_int("HUMANIZER_PERPLEXITY_STRIDE_TOKENS", 256)),
            perplexity_low_threshold=max(1.0, _get_float("HUMANIZER_PERPLEXITY_LOW_THRESHOLD", 15.0)),
            perplexity_high_threshold=max(10.0, _get_float("HUMANIZER_PERPLEXITY_HIGH_THRESHOLD", 120.0)),
            spacy_model_name=os.getenv("HUMANIZER_SPACY_MODEL_NAME", "en_core_web_sm").strip() or "en_core_web_sm",
            rewriter_model=os.getenv("HUMANIZER_MODEL_NAME", "").strip() or resolved_settings.vertex_model,
            model_local_files_only=_get_bool("HUMANIZER_MODEL_LOCAL_FILES_ONLY", False),
            preserve_first_person_in_discussion=_get_bool("HUMANIZER_PRESERVE_FIRST_PERSON_IN_DISCUSSION", True),
        )
