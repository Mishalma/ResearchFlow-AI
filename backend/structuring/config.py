from __future__ import annotations

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
    reducer_model: str | None = None
    lexical_min_score: float = 0.0
    section_names: tuple[str, ...] = field(default_factory=lambda: REQUIRED_STRUCTURING_SECTIONS)
    title_candidate_limit: int = 3
    max_key_points: int = 4

    @property
    def chunk_size_chars(self) -> int:
        return self.chunk_size_tokens * self.approx_chars_per_token

    @property
    def chunk_overlap_chars(self) -> int:
        return self.chunk_overlap_tokens * self.approx_chars_per_token

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "StructuringConfig":
        resolved_settings = settings or get_settings()
        return cls(
            reducer_model=resolved_settings.vertex_model,
        )
