from __future__ import annotations

import logging

from structuring.config import StructuringConfig
from structuring.schemas import TextChunk

logger = logging.getLogger("papereasy.backend.structuring.chunking")

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - optional dependency
    RecursiveCharacterTextSplitter = None


def normalize_source_text(text: str, max_chars: int | None = None) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if max_chars is not None and max_chars > 0:
        return normalized[:max_chars]
    return normalized


def chunk_source_text(
    text: str,
    config: StructuringConfig,
) -> list[TextChunk]:
    normalized = normalize_source_text(text)
    if not normalized:
        return []

    chunks = _chunk_with_splitter(normalized, config)
    if not chunks:
        chunks = _chunk_deterministically(normalized, config)
    return chunks


def _chunk_with_splitter(
    text: str,
    config: StructuringConfig,
) -> list[TextChunk]:
    if RecursiveCharacterTextSplitter is None:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size_chars,
        chunk_overlap=config.chunk_overlap_chars,
        separators=["\n\n", "\n", ". ", "; ", " ", ""],
        length_function=len,
        keep_separator=False,
    )
    fragments = splitter.split_text(text)
    if not fragments:
        return []

    chunks: list[TextChunk] = []
    search_offset = 0
    for index, fragment in enumerate(fragments, start=1):
        stripped_fragment = fragment.strip()
        if not stripped_fragment:
            continue
        aligned_start = text.find(stripped_fragment, search_offset)
        if aligned_start < 0:
            logger.debug("Falling back to deterministic chunking because splitter alignment failed.")
            return []
        aligned_end = aligned_start + len(stripped_fragment)
        chunks.append(
            TextChunk(
                chunk_id=f"chunk-{index:04d}",
                text=stripped_fragment,
                start_char=aligned_start,
                end_char=aligned_end,
            )
        )
        search_offset = max(aligned_end - config.chunk_overlap_chars, aligned_start + 1)
    return chunks


def _chunk_deterministically(
    text: str,
    config: StructuringConfig,
) -> list[TextChunk]:
    size = max(config.chunk_size_chars, 1)
    overlap = min(max(config.chunk_overlap_chars, 0), max(size - 1, 0))
    chunks: list[TextChunk] = []

    start = 0
    chunk_index = 1
    while start < len(text):
        tentative_end = min(start + size, len(text))
        end = _choose_boundary(text, start, tentative_end)
        if end <= start:
            end = tentative_end

        raw_slice = text[start:end]
        leading = len(raw_slice) - len(raw_slice.lstrip())
        trailing = len(raw_slice) - len(raw_slice.rstrip())
        actual_start = start + leading
        actual_end = end - trailing
        if actual_end <= actual_start:
            actual_start = start
            actual_end = end

        chunks.append(
            TextChunk(
                chunk_id=f"chunk-{chunk_index:04d}",
                text=text[actual_start:actual_end],
                start_char=actual_start,
                end_char=actual_end,
            )
        )
        chunk_index += 1
        if actual_end >= len(text):
            break

        next_start = max(0, end - overlap)
        if next_start <= start:
            next_start = min(start + max(size - overlap, 1), len(text))
        start = next_start

    return chunks


def _choose_boundary(text: str, start: int, tentative_end: int) -> int:
    if tentative_end >= len(text):
        return len(text)

    lookback_window = text[start:tentative_end]
    boundary_markers = ("\n\n", "\n", ". ", "; ", " ")
    for marker in boundary_markers:
        marker_index = lookback_window.rfind(marker)
        if marker_index > int(len(lookback_window) * 0.6):
            return start + marker_index + len(marker)
    return tentative_end
