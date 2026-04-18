from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Iterable

from humanizer.schemas import HumanizedPaperDraft
from models.generation import GeneratedPaper

SECTION_ORDER = (
    "abstract",
    "introduction",
    "related_work",
    "methodology",
    "results",
    "discussion",
    "limitations",
    "conclusion",
)

CITATION_PATTERN = re.compile(r"\[[0-9,\-\s]+\]|\\cite[t|p]?\{[^}]+\}")
QUOTE_PATTERN = re.compile(r"\"[^\"]+\"|'[^']+'|“[^”]+”")
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_whitespace(value: object) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def build_section_map(*, humanized_draft: object | None, paper_snapshot: object | None) -> dict[str, str]:
    section_map: dict[str, str] = {}
    if humanized_draft not in (None, "", {}):
        try:
            parsed_humanized = HumanizedPaperDraft.model_validate(humanized_draft)
            for section_name in SECTION_ORDER:
                if section_name in parsed_humanized.sections:
                    section_map[section_name] = parsed_humanized.sections[section_name].text.strip()
        except Exception:
            section_map = {}

    if paper_snapshot not in (None, "", {}):
        parsed_paper = GeneratedPaper.model_validate(paper_snapshot)
        section_map.setdefault("abstract", parsed_paper.paper.abstract.strip())
        section_map.setdefault("introduction", parsed_paper.paper.sections.introduction.strip())
        section_map.setdefault("related_work", parsed_paper.paper.sections.related_work.strip())
        section_map.setdefault("methodology", parsed_paper.paper.sections.methodology.strip())
        section_map.setdefault("results", parsed_paper.paper.sections.results.strip())
        section_map.setdefault("discussion", parsed_paper.paper.sections.discussion.strip())
        section_map.setdefault("limitations", parsed_paper.paper.sections.limitations.strip())
        section_map.setdefault("conclusion", parsed_paper.paper.sections.conclusion.strip())
    return {name: section_map.get(name, "").strip() for name in SECTION_ORDER}


def build_section_ai_scores(humanized_draft: object | None) -> dict[str, float]:
    if humanized_draft in (None, "", {}):
        return {}
    try:
        parsed = HumanizedPaperDraft.model_validate(humanized_draft)
    except Exception:
        return {}
    scores: dict[str, float] = {}
    # Humanizer stores section-level AI-pattern score inside report paragraph aggregation only indirectly,
    # so the route uses the section reports' average after-score when present in metadata.
    for section_name, section in parsed.sections.items():
        paragraph_scores = [item.ai_pattern_score_after for item in section.report.paragraph_reports]
        if paragraph_scores:
            scores[section_name] = round(sum(paragraph_scores) / len(paragraph_scores), 4)
    return scores


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[tuple[int, int, str]]:
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [(0, len(normalized), normalized)]

    paragraphs: list[tuple[int, int, str]] = []
    cursor = 0
    for block in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", normalized):
        start, end = block.span()
        segment = normalized[start:end].strip()
        if segment:
            paragraphs.append((start, end, segment))
        cursor = end
    if not paragraphs:
        paragraphs = [(0, len(normalized), normalized)]

    chunks: list[tuple[int, int, str]] = []
    index = 0
    while index < len(normalized):
        chunk_end = min(len(normalized), index + chunk_size)
        preferred_end = chunk_end
        boundary = normalized.rfind("\n\n", index, chunk_end)
        if boundary > index + (chunk_size // 3):
            preferred_end = boundary
        if preferred_end <= index:
            preferred_end = chunk_end
        text_chunk = normalized[index:preferred_end].strip()
        if text_chunk:
            chunks.append((index, preferred_end, text_chunk))
        if preferred_end >= len(normalized):
            break
        index = max(preferred_end - overlap, index + 1)
    return chunks


def extract_nearby_citations(text: str, *, start_char: int, end_char: int, window: int) -> list[str]:
    left = max(0, start_char - window)
    right = min(len(text), end_char + window)
    region = text[left:right]
    return [match.group(0) for match in CITATION_PATTERN.finditer(region)]


def span_inside_quote(text: str, *, start_char: int, end_char: int) -> bool:
    for match in QUOTE_PATTERN.finditer(text):
        if match.start() <= start_char and end_char <= match.end():
            return True
    return False


def build_reference_lookup(reference_lines: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for reference in reference_lines:
        normalized = normalize_whitespace(reference)
        if not normalized:
            continue
        lowered = normalized.lower()
        lookup[lowered] = normalized
        title_match = re.search(r'"([^"]+)"', normalized)
        if title_match:
            lookup[normalize_whitespace(title_match.group(1)).lower()] = normalized
    return lookup


def bibliography_has_source(
    *,
    title: str | None,
    url: str | None,
    bibliography_lookup: dict[str, str],
) -> bool:
    title_key = normalize_whitespace(title).lower()
    if title_key and title_key in bibliography_lookup:
        return True
    if url:
        lowered_url = str(url).strip().lower()
        return any(lowered_url in value.lower() for value in bibliography_lookup.values())
    return False


def author_strings(author_metadata: object) -> list[str]:
    if author_metadata is None:
        return []
    if isinstance(author_metadata, dict):
        values = author_metadata.values()
    elif isinstance(author_metadata, (list, tuple, set)):
        values = author_metadata
    else:
        values = [author_metadata]
    return [normalize_whitespace(value).lower() for value in values if normalize_whitespace(value)]


def looks_like_self_overlap(
    *,
    matched_source_title: str | None,
    matched_source_url: str | None,
    author_metadata: object,
) -> bool:
    author_tokens = author_strings(author_metadata)
    if not author_tokens:
        return False
    source_blob = " ".join(
        part for part in [normalize_whitespace(matched_source_title), normalize_whitespace(matched_source_url)] if part
    ).lower()
    if not source_blob:
        return False
    return any(token and token in source_blob for token in author_tokens)


def summarize_status_counts(statuses: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses:
        normalized = normalize_whitespace(status)
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def callback_store_root(base_dir: Path) -> Path:
    return (base_dir / "originality_callbacks").resolve()


def persist_callback_payload(*, base_dir: Path, scan_id: str, event_name: str, payload: dict[str, Any]) -> Path:
    root = callback_store_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{sanitize_identifier(scan_id)}__{sanitize_identifier(event_name)}.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def load_callback_payload(*, base_dir: Path, scan_id: str, event_name: str) -> dict[str, Any] | None:
    target = callback_store_root(base_dir) / f"{sanitize_identifier(scan_id)}__{sanitize_identifier(event_name)}.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


async def wait_for_callback_payload(
    *,
    base_dir: Path,
    scan_id: str,
    event_name: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any] | None:
    remaining = max(0.0, timeout_seconds)
    while remaining >= 0.0:
        payload = load_callback_payload(base_dir=base_dir, scan_id=scan_id, event_name=event_name)
        if payload is not None:
            return payload
        if remaining <= 0.0:
            break
        await asyncio.sleep(poll_interval_seconds)
        remaining -= poll_interval_seconds
    return None


def sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return cleaned or "event"
