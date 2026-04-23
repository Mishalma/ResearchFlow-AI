from __future__ import annotations

import re
from statistics import mean, pstdev

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]*")


def split_sentences(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []
    return [chunk.strip() for chunk in _SENTENCE_SPLIT_PATTERN.split(normalized) if chunk.strip()]


def iter_sentence_spans(text: str) -> list[tuple[int, int, str]]:
    normalized = text or ""
    spans: list[tuple[int, int, str]] = []
    start = 0
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", normalized):
        raw_text = match.group(0)
        stripped = raw_text.strip()
        if not stripped:
            continue
        offset = raw_text.find(stripped)
        span_start = match.start() + max(0, offset)
        span_end = span_start + len(stripped)
        spans.append((span_start, span_end, stripped))
        start = match.end()
    if not spans and normalized.strip():
        stripped = normalized.strip()
        start_index = normalized.find(stripped)
        spans.append((start_index, start_index + len(stripped), stripped))
    return spans


def tokenize_words(text: str) -> list[str]:
    return [token.lower() for token in _WORD_PATTERN.findall(text or "")]


def stylometry_profile(text: str) -> dict[str, float]:
    sentences = split_sentences(text)
    tokens = tokenize_words(text)
    if not tokens:
        return {
            "type_token_ratio": 0.0,
            "average_sentence_length": 0.0,
            "sentence_length_variance": 0.0,
            "paragraph_monotony": 0.0,
            "score": 0.0,
        }

    unique_tokens = len(set(tokens))
    type_token_ratio = unique_tokens / len(tokens)
    sentence_lengths = [len(tokenize_words(sentence)) for sentence in sentences if tokenize_words(sentence)]
    average_sentence_length = mean(sentence_lengths) if sentence_lengths else 0.0
    sentence_length_variance = pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text or "") if paragraph.strip()]
    paragraph_lengths = [len(tokenize_words(paragraph)) for paragraph in paragraphs if tokenize_words(paragraph)]
    paragraph_variance = pstdev(paragraph_lengths) if len(paragraph_lengths) > 1 else 0.0

    low_ttr_risk = 1.0 if type_token_ratio <= 0.42 else max(0.0, 1.0 - ((type_token_ratio - 0.42) / 0.23))
    low_variance_risk = 1.0 if sentence_length_variance <= 3.5 else max(
        0.0,
        1.0 - ((sentence_length_variance - 3.5) / 8.5),
    )
    paragraph_monotony = 1.0 if paragraph_variance <= 8.0 and len(paragraph_lengths) > 1 else 0.0
    score = (low_ttr_risk * 0.45) + (low_variance_risk * 0.40) + (paragraph_monotony * 0.15)

    return {
        "type_token_ratio": round(type_token_ratio, 4),
        "average_sentence_length": round(float(average_sentence_length), 4),
        "sentence_length_variance": round(float(sentence_length_variance), 4),
        "paragraph_monotony": round(float(paragraph_monotony), 4),
        "score": round(max(0.0, min(1.0, score)), 4),
    }
