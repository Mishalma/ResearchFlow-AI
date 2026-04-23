from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.config import Settings, get_settings
from structuring.schemas import REQUIRED_STRUCTURING_SECTIONS


@dataclass(frozen=True)
class StructuringConfig:
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 128
    approx_chars_per_token: int = 4
    top_k_per_section: int = 4
    lexical_candidate_pool: int = 6
    minimum_source_chars: int = 200
    quote_max_chars: int = 180
    google_embedding_model: str = "text-embedding-005"
    local_embedding_model: str = "all-MiniLM-L6-v2"
    use_llm_reducer: bool = False
    reducer_model: str | None = None
    lexical_min_score: float = 0.0
    section_names: tuple[str, ...] = field(default_factory=lambda: REQUIRED_STRUCTURING_SECTIONS)
    title_candidate_limit: int = 3
    max_key_points: int = 4
    max_parallel_section_reductions: int = 4

    @property
    def chunk_size_chars(self) -> int:
        return self.chunk_size_tokens * self.approx_chars_per_token

    @property
    def chunk_overlap_chars(self) -> int:
        return self.chunk_overlap_tokens * self.approx_chars_per_token

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "StructuringConfig":
        resolved_settings = settings or get_settings()
        use_llm_reducer = os.getenv("STRUCTURING_USE_LLM_REDUCER")
        normalized_reducer_flag = (
            use_llm_reducer.strip().lower() in {"1", "true", "yes", "on"}
            if use_llm_reducer is not None
            else False
        )
        return cls(
            use_llm_reducer=normalized_reducer_flag,
            reducer_model=resolved_settings.vertex_model,
            max_parallel_section_reductions=max(
                1,
                int(os.getenv("STRUCTURING_MAX_PARALLEL_SECTIONS", "4")),
            ),
        )
