from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from statistics import mean, pstdev
from typing import Iterable

from humanizer.config import HumanizerConfig
from humanizer.schemas import DetectedPattern
from humanizer.utils import SECTION_LABELS, split_paragraphs, split_sentences, tokenize

logger = logging.getLogger("papereasy.backend.humanizer.detectors")

TRANSITION_MARKERS = (
    "furthermore",
    "moreover",
    "additionally",
    "therefore",
    "overall",
    "notably",
    "in conclusion",
    "consequently",
    "thus",
)
HEDGE_MARKERS = (
    "it is worth noting",
    "it is important to",
    "it can be observed",
    "it should be noted",
    "may",
    "might",
    "suggests",
    "appears",
    "could",
    "potentially",
)
MINOR_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "by",
    "on",
    "as",
    "at",
    "this",
    "that",
    "these",
    "those",
}


@dataclass(frozen=True)
class ParagraphAnalysis:
    paragraph_index: int
    text: str
    sentence_lengths: list[int]
    cadence_score: float
    ai_pattern_score: float
    detected_patterns: list[DetectedPattern] = field(default_factory=list)


@dataclass(frozen=True)
class SectionAnalysis:
    section_name: str
    text: str
    paragraphs: list[ParagraphAnalysis]
    detected_patterns: list[DetectedPattern]
    cadence_score: float
    passive_ratio: float
    hedge_score: float
    transition_score: float
    lexical_repetition_score: float
    paragraph_monotony_score: float
    ai_pattern_score: float


class PassiveVoiceAnalyzer:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def score_text(self, text: str) -> tuple[float, list[str]]:
        nlp = _load_spacy_model(self.model_name)
        if nlp is None:
            return 0.0, []

        doc = nlp(text)
        passive_sentences: list[str] = []
        sentence_count = 0
        for sent in doc.sents:
            sentence = sent.text.strip()
            if not sentence:
                continue
            sentence_count += 1
            deps = {token.dep_.lower() for token in sent}
            if "nsubjpass" in deps or "auxpass" in deps:
                passive_sentences.append(sentence)
        if sentence_count == 0:
            return 0.0, []
        return round(len(passive_sentences) / sentence_count, 4), passive_sentences


def analyze_section(
    *,
    section_name: str,
    text: str,
    config: HumanizerConfig,
    logger_: logging.Logger | None = None,
) -> SectionAnalysis:
    active_logger = logger_ or logger
    paragraphs = split_paragraphs(text)
    paragraph_analyses = [
        _analyze_paragraph(paragraph_index=index, text=paragraph)
        for index, paragraph in enumerate(paragraphs)
    ]

    cadence_score = round(mean([analysis.cadence_score for analysis in paragraph_analyses]), 4) if paragraph_analyses else 0.0
    hedge_score, hedge_patterns = _detect_overused_hedges(section_name=section_name, paragraphs=paragraphs)
    transition_score, transition_patterns = _detect_repetitive_transitions(paragraphs=paragraphs)
    lexical_repetition_score, lexical_patterns = _detect_lexical_repetition(paragraphs=paragraphs)
    paragraph_monotony_score, paragraph_patterns = _detect_paragraph_monotony(paragraphs=paragraphs)

    passive_ratio, passive_sentences = PassiveVoiceAnalyzer(config.spacy_model_name).score_text(text)
    passive_patterns: list[DetectedPattern] = []
    if passive_ratio >= 0.45:
        passive_patterns.append(
            DetectedPattern(
                pattern_type="passive_voice_overuse",
                severity=min(1.0, passive_ratio),
                location=f"section:{section_name}",
                evidence=passive_sentences[:3],
            )
        )

    detected_patterns: list[DetectedPattern] = []
    detected_patterns.extend(hedge_patterns)
    detected_patterns.extend(transition_patterns)
    detected_patterns.extend(lexical_patterns)
    detected_patterns.extend(paragraph_patterns)
    detected_patterns.extend(passive_patterns)
    for paragraph in paragraph_analyses:
        detected_patterns.extend(paragraph.detected_patterns)

    ai_pattern_score = _aggregate_ai_pattern_score(
        cadence_score=cadence_score,
        hedge_score=hedge_score,
        passive_ratio=passive_ratio,
        transition_score=transition_score,
        lexical_repetition_score=lexical_repetition_score,
        paragraph_monotony_score=paragraph_monotony_score,
    )
    active_logger.info(
        "Humanizer section %s scores cadence=%.3f hedge=%.3f passive=%.3f transition=%.3f lexical=%.3f monotony=%.3f ai=%.3f",
        section_name,
        cadence_score,
        hedge_score,
        passive_ratio,
        transition_score,
        lexical_repetition_score,
        paragraph_monotony_score,
        ai_pattern_score,
    )
    return SectionAnalysis(
        section_name=section_name,
        text=text,
        paragraphs=paragraph_analyses,
        detected_patterns=detected_patterns,
        cadence_score=cadence_score,
        passive_ratio=passive_ratio,
        hedge_score=hedge_score,
        transition_score=transition_score,
        lexical_repetition_score=lexical_repetition_score,
        paragraph_monotony_score=paragraph_monotony_score,
        ai_pattern_score=ai_pattern_score,
    )


def _analyze_paragraph(*, paragraph_index: int, text: str) -> ParagraphAnalysis:
    sentences = split_sentences(text)
    sentence_lengths = [len(tokenize(sentence)) for sentence in sentences if tokenize(sentence)]
    cadence_score = _sentence_uniformity_score(sentence_lengths)
    patterns: list[DetectedPattern] = []
    if cadence_score >= 0.62:
        patterns.append(
            DetectedPattern(
                pattern_type="uniform_sentence_cadence",
                severity=cadence_score,
                location=f"paragraph:{paragraph_index}",
                evidence=sentences[:3],
            )
        )
    repeated_openings = _detect_repeated_openings(sentences)
    if repeated_openings:
        patterns.append(
            DetectedPattern(
                pattern_type="repeated_sentence_openings",
                severity=min(1.0, 0.35 + (0.2 * len(repeated_openings))),
                location=f"paragraph:{paragraph_index}",
                evidence=repeated_openings,
            )
        )
    ai_pattern_score = min(
        1.0,
        round(
            (cadence_score * 0.7)
            + (0.15 * len(repeated_openings))
            + (0.15 if len(sentences) >= 3 and len(set(sentence_lengths)) <= 2 else 0.0),
            4,
        ),
    )
    return ParagraphAnalysis(
        paragraph_index=paragraph_index,
        text=text,
        sentence_lengths=sentence_lengths,
        cadence_score=round(cadence_score, 4),
        ai_pattern_score=ai_pattern_score,
        detected_patterns=patterns,
    )


def _sentence_uniformity_score(sentence_lengths: list[int]) -> float:
    if len(sentence_lengths) <= 1:
        return 0.0
    mean_length = mean(sentence_lengths)
    if mean_length <= 0:
        return 0.0
    deviation = pstdev(sentence_lengths)
    coefficient_of_variation = deviation / mean_length if mean_length else 0.0
    repeated_lengths = sum(count for _, count in Counter(sentence_lengths).items() if count > 1)
    cluster_penalty = repeated_lengths / max(len(sentence_lengths), 1)
    uniformity = max(0.0, 1.0 - min(1.0, coefficient_of_variation))
    return round(min(1.0, (uniformity * 0.75) + (cluster_penalty * 0.25)), 4)


def _detect_overused_hedges(
    *,
    section_name: str,
    paragraphs: list[str],
) -> tuple[float, list[DetectedPattern]]:
    section_text = " ".join(paragraphs).lower()
    total_sentences = max(1, sum(len(split_sentences(paragraph)) for paragraph in paragraphs))
    counts = Counter(marker for marker in HEDGE_MARKERS if marker in section_text)
    repeated = {marker: count for marker, count in counts.items() if count >= 2}
    hedge_ratio = min(1.0, sum(counts.values()) / max(total_sentences * 2, 1))

    if section_name in {"results", "discussion", "limitations"}:
        hedge_ratio = max(0.0, hedge_ratio - 0.1)

    patterns: list[DetectedPattern] = []
    if repeated or hedge_ratio >= 0.55:
        evidence = [f"{marker} x{count}" for marker, count in repeated.items()] or list(counts.keys())[:3]
        patterns.append(
            DetectedPattern(
                pattern_type="overused_hedging",
                severity=round(min(1.0, hedge_ratio + (0.08 * len(repeated))), 4),
                location=f"section:{section_name}",
                evidence=evidence,
            )
        )
    return round(hedge_ratio, 4), patterns


def _detect_repetitive_transitions(*, paragraphs: list[str]) -> tuple[float, list[DetectedPattern]]:
    sentence_starts: list[str] = []
    for paragraph in paragraphs:
        for sentence in split_sentences(paragraph):
            lowered = sentence.lower()
            for marker in TRANSITION_MARKERS:
                if lowered.startswith(marker):
                    sentence_starts.append(marker)
                    break
    if not sentence_starts:
        return 0.0, []

    counts = Counter(sentence_starts)
    repeated = {marker: count for marker, count in counts.items() if count >= 2}
    score = min(1.0, sum(repeated.values()) / max(len(sentence_starts), 1))
    patterns: list[DetectedPattern] = []
    if repeated:
        patterns.append(
            DetectedPattern(
                pattern_type="repetitive_transitions",
                severity=round(score, 4),
                location="section",
                evidence=[f"{marker} x{count}" for marker, count in repeated.items()],
            )
        )
    return round(score, 4), patterns


def _detect_lexical_repetition(*, paragraphs: list[str]) -> tuple[float, list[DetectedPattern]]:
    tokens = [
        token
        for paragraph in paragraphs
        for token in tokenize(paragraph)
        if token not in MINOR_STOPWORDS and len(token) > 4
    ]
    if not tokens:
        return 0.0, []
    counts = Counter(tokens)
    repeated = {token: count for token, count in counts.items() if count >= 4}
    repetition_score = min(1.0, len(repeated) / max(6, len(counts)))
    patterns: list[DetectedPattern] = []
    if repeated:
        patterns.append(
            DetectedPattern(
                pattern_type="lexical_repetition",
                severity=round(repetition_score, 4),
                location="section",
                evidence=[f"{token} x{count}" for token, count in repeated.items()],
            )
        )
    return round(repetition_score, 4), patterns


def _detect_paragraph_monotony(*, paragraphs: list[str]) -> tuple[float, list[DetectedPattern]]:
    if len(paragraphs) < 2:
        return 0.0, []
    openings = [_paragraph_opening(paragraph) for paragraph in paragraphs]
    lengths = [len(tokenize(paragraph)) for paragraph in paragraphs]
    repeated_openings = [opening for opening, count in Counter(openings).items() if opening and count >= 2]
    mean_length = mean(lengths)
    deviation = pstdev(lengths) if len(lengths) > 1 else 0.0
    length_similarity = 1.0 - min(1.0, deviation / max(mean_length, 1))
    score = min(1.0, (0.5 * length_similarity) + (0.25 * (len(repeated_openings) / max(len(paragraphs), 1))) + (0.25 if len(set(lengths)) <= 2 else 0.0))
    patterns: list[DetectedPattern] = []
    if score >= 0.45:
        evidence = [f"opening:{opening}" for opening in repeated_openings[:3]]
        patterns.append(
            DetectedPattern(
                pattern_type="paragraph_monotony",
                severity=round(score, 4),
                location="section",
                evidence=evidence,
            )
        )
    return round(score, 4), patterns


def _detect_repeated_openings(sentences: Iterable[str]) -> list[str]:
    openings = [sentence.split()[:2] for sentence in sentences if sentence.strip()]
    normalized = [" ".join(words).lower() for words in openings if words]
    return [opening for opening, count in Counter(normalized).items() if count >= 2]


def _paragraph_opening(paragraph: str) -> str:
    sentences = split_sentences(paragraph)
    if not sentences:
        return ""
    return " ".join(sentences[0].split()[:3]).lower()


def _aggregate_ai_pattern_score(
    *,
    cadence_score: float,
    hedge_score: float,
    passive_ratio: float,
    transition_score: float,
    lexical_repetition_score: float,
    paragraph_monotony_score: float,
) -> float:
    return round(
        min(
            1.0,
            (cadence_score * 0.24)
            + (hedge_score * 0.16)
            + (passive_ratio * 0.18)
            + (transition_score * 0.14)
            + (lexical_repetition_score * 0.14)
            + (paragraph_monotony_score * 0.14),
        ),
        4,
    )


@lru_cache(maxsize=2)
def _load_spacy_model(model_name: str):
    try:
        import spacy
    except ImportError:
        logger.warning("spaCy is unavailable; passive voice detection will be skipped.")
        return None

    try:
        return spacy.load(model_name)
    except Exception as exc:
        logger.warning("Unable to load spaCy model '%s': %s", model_name, exc)
        return None
