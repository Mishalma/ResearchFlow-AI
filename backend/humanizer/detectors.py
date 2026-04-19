"""Multi-signal AI-pattern detection utilities for the humanizer agent."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from statistics import mean, pstdev

try:
    import nltk
except ImportError as exc:  # pragma: no cover - dependency dependent
    nltk = None
    logging.getLogger(__name__).warning(
        "nltk is not installed; detector module will use regex-based fallbacks: %s",
        exc,
    )

if nltk is not None:
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        try:
            nltk.download("punkt", quiet=True)
        except Exception as exc:  # pragma: no cover - environment dependent
            logging.getLogger(__name__).warning(
                "Unable to download nltk punkt tokenizer: %s",
                exc,
            )
    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        try:
            nltk.download("stopwords", quiet=True)
        except Exception as exc:  # pragma: no cover - environment dependent
            logging.getLogger(__name__).warning(
                "Unable to download nltk stopwords corpus: %s",
                exc,
            )
    try:
        from nltk.corpus import stopwords
        from nltk.tokenize import sent_tokenize, word_tokenize
    except Exception as exc:  # pragma: no cover - dependency dependent
        stopwords = None
        sent_tokenize = None
        word_tokenize = None
        logging.getLogger(__name__).warning(
            "nltk tokenizers or corpora are unavailable; detector module will use fallbacks: %s",
            exc,
        )
else:
    stopwords = None
    sent_tokenize = None
    word_tokenize = None

from humanizer.config import HumanizerConfig
from humanizer.schemas import DetectedPattern

logger = logging.getLogger(__name__)

TRANSITION_MARKERS = (
    "furthermore",
    "moreover",
    "in addition",
    "it is worth noting",
    "it is important to",
    "in conclusion",
    "notably",
    "importantly",
    "additionally",
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
_FALLBACK_STOPWORDS = {
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
    "be",
    "been",
    "being",
    "by",
    "on",
    "as",
    "at",
    "this",
    "that",
    "these",
    "those",
}
_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]*")
_PASSIVE_REGEX = re.compile(
    r"\b(?:was|were|been|is|are|be|being)\b\s+\b\w+(?:ed|en|wn|ne|lt|rt)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParagraphAnalysis:
    """Compatibility paragraph-level detector summary."""

    paragraph_index: int
    text: str
    sentence_lengths: list[int]
    cadence_score: float
    ai_pattern_score: float
    detected_patterns: list[DetectedPattern] = field(default_factory=list)


@dataclass(frozen=True)
class SectionAnalysis:
    """Compatibility section-level detector summary."""

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


def _safe_sent_tokenize(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []
    if sent_tokenize is None:
        return [
            chunk.strip()
            for chunk in re.split(r"(?<=[.!?])\s+", normalized)
            if chunk.strip()
        ]
    try:
        return [sentence.strip() for sentence in sent_tokenize(normalized) if sentence.strip()]
    except Exception as exc:
        logger.warning("nltk sentence tokenization failed; using regex fallback: %s", exc)
        return [
            chunk.strip()
            for chunk in re.split(r"(?<=[.!?])\s+", normalized)
            if chunk.strip()
        ]


def _safe_word_tokenize(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []
    if word_tokenize is None:
        return _TOKEN_PATTERN.findall(normalized)
    try:
        return [token for token in word_tokenize(normalized) if token.strip()]
    except Exception as exc:
        logger.warning("nltk word tokenization failed; using regex fallback: %s", exc)
        return _TOKEN_PATTERN.findall(normalized)


def _content_tokens(text: str) -> list[str]:
    stopword_set = _get_stopword_set()
    content: list[str] = []
    for token in _safe_word_tokenize(text):
        normalized = token.lower()
        if not _TOKEN_PATTERN.fullmatch(normalized):
            continue
        if normalized in stopword_set:
            continue
        content.append(normalized)
    return content


@lru_cache(maxsize=1)
def _get_stopword_set() -> set[str]:
    try:
        if stopwords is None:
            raise LookupError("nltk stopwords corpus is unavailable")
        return set(stopwords.words("english"))
    except Exception as exc:
        logger.warning("nltk stopwords unavailable; using fallback list: %s", exc)
        return set(_FALLBACK_STOPWORDS)


def burstiness_score(text: str) -> float:
    """Return sentence-length burstiness as std_dev / mean."""

    sentences = _safe_sent_tokenize(text)
    if len(sentences) < 3:
        return 0.0
    lengths = [len(_content_tokens(sentence) or _safe_word_tokenize(sentence)) for sentence in sentences]
    mean_length = mean(lengths)
    if mean_length <= 0:
        return 0.0
    return round(pstdev(lengths) / mean_length, 4)


def lexical_repetition_score(text: str) -> float:
    """Return repeated content-token ratio across a 5-sentence sliding window."""

    sentences = _safe_sent_tokenize(text)
    if not sentences:
        return 0.0

    repeated_tokens = 0
    total_tokens = 0
    for start in range(0, len(sentences)):
        window = sentences[start : start + 5]
        if not window:
            continue
        tokens: list[str] = []
        for sentence in window:
            tokens.extend(_content_tokens(sentence))
        if not tokens:
            continue
        counts = Counter(tokens)
        repeated_tokens += sum(count - 1 for count in counts.values() if count > 1)
        total_tokens += len(tokens)

    if total_tokens == 0:
        return 0.0
    return round(min(1.0, repeated_tokens / total_tokens), 4)


def transition_uniformity_score(text: str) -> float:
    """Return the frequency of repeated stock transitions per sentence."""

    sentences = _safe_sent_tokenize(text)
    if not sentences:
        return 0.0

    flagged_count = 0
    for sentence in sentences:
        lowered = sentence.strip().lower()
        if any(lowered.startswith(marker) for marker in TRANSITION_MARKERS):
            flagged_count += 1
    return round(flagged_count / len(sentences), 4)


def sentence_cadence_score(text: str) -> float:
    """Return a normalized cadence-uniformity score where higher is more AI-like."""

    sentences = _safe_sent_tokenize(text)
    if len(sentences) < 2:
        return 0.0
    lengths = [len(_safe_word_tokenize(sentence)) for sentence in sentences]
    variance = pstdev(lengths) ** 2 if len(lengths) > 1 else 0.0
    if variance <= 8:
        return 1.0
    if variance >= 20:
        return 0.0
    normalized = 1.0 - ((variance - 8.0) / 12.0)
    return round(max(0.0, min(1.0, normalized)), 4)


class PassiveVoiceAnalyzer:
    """Analyze passive-voice usage with spaCy or a regex fallback."""

    def __init__(self, model_name: str = "en_core_web_sm"):
        self.model_name = model_name

    def score_text(self, text: str) -> tuple[float, list[str]]:
        """Return passive voice ratio and example evidence sentences."""

        sentences = _safe_sent_tokenize(text)
        if not sentences:
            return 0.0, []

        nlp = _load_spacy_model(self.model_name)
        if nlp is not None:
            try:
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
            except Exception as exc:
                logger.warning(
                    "spaCy passive voice analysis failed; using regex fallback: %s",
                    exc,
                )

        passive_sentences = [
            sentence
            for sentence in sentences
            if _PASSIVE_REGEX.search(sentence)
        ]
        return round(len(passive_sentences) / len(sentences), 4), passive_sentences


def passive_voice_ratio(text: str) -> float:
    """Return passive constructions per sentence."""

    ratio, _ = PassiveVoiceAnalyzer().score_text(text)
    return ratio


def _normalize_burstiness_for_ai_score(value: float) -> float:
    if value <= 0.2:
        return 1.0
    if value >= 0.8:
        return 0.0
    normalized = 1.0 - ((value - 0.2) / 0.6)
    return round(max(0.0, min(1.0, normalized)), 4)


def composite_ai_score(text: str) -> dict[str, float]:
    """Aggregate the detector signals into one normalized AI-pattern score."""

    if not (text or "").strip():
        return {
            "burstiness": 0.0,
            "lexical_repetition": 0.0,
            "transition_uniformity": 0.0,
            "cadence_uniformity": 0.0,
            "passive_voice_ratio": 0.0,
            "composite_score": 0.0,
        }

    burstiness = burstiness_score(text)
    lexical_repetition = lexical_repetition_score(text)
    transition_uniformity = transition_uniformity_score(text)
    cadence_uniformity = sentence_cadence_score(text)
    passive_ratio = passive_voice_ratio(text)
    composite = (
        (_normalize_burstiness_for_ai_score(burstiness) * 0.30)
        + (transition_uniformity * 0.20)
        + (cadence_uniformity * 0.25)
        + (lexical_repetition * 0.15)
        + (passive_ratio * 0.10)
    )
    return {
        "burstiness": round(burstiness, 4),
        "lexical_repetition": round(lexical_repetition, 4),
        "transition_uniformity": round(transition_uniformity, 4),
        "cadence_uniformity": round(cadence_uniformity, 4),
        "passive_voice_ratio": round(passive_ratio, 4),
        "composite_score": round(max(0.0, min(1.0, composite)), 4),
    }


def analyze_section(
    *,
    section_name: str,
    text: str,
    config: HumanizerConfig | None = None,
    logger_: logging.Logger | None = None,
) -> SectionAnalysis:
    """Compatibility helper returning a structured section analysis."""

    active_logger = logger_ or logger
    section_scores = composite_ai_score(text)
    sentences = _safe_sent_tokenize(text)
    paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", (text or "").strip())
        if block.strip()
    ]
    paragraph_analyses: list[ParagraphAnalysis] = []
    for index, paragraph in enumerate(paragraphs or [text.strip()]):
        paragraph_scores = composite_ai_score(paragraph)
        paragraph_sentences = _safe_sent_tokenize(paragraph)
        paragraph_lengths = [len(_safe_word_tokenize(sentence)) for sentence in paragraph_sentences]
        detected: list[DetectedPattern] = []
        if paragraph_scores["cadence_uniformity"] >= 0.7:
            detected.append(
                DetectedPattern(
                    pattern_type="uniform_sentence_cadence",
                    severity=paragraph_scores["cadence_uniformity"],
                    location=f"paragraph:{index}",
                    evidence=paragraph_sentences[:3],
                )
            )
        if paragraph_scores["transition_uniformity"] > 0:
            detected.append(
                DetectedPattern(
                    pattern_type="repetitive_transitions",
                    severity=paragraph_scores["transition_uniformity"],
                    location=f"paragraph:{index}",
                    evidence=[
                        sentence
                        for sentence in paragraph_sentences
                        if any(sentence.lower().startswith(marker) for marker in TRANSITION_MARKERS)
                    ][:3],
                )
            )
        paragraph_analyses.append(
            ParagraphAnalysis(
                paragraph_index=index,
                text=paragraph,
                sentence_lengths=paragraph_lengths,
                cadence_score=paragraph_scores["cadence_uniformity"],
                ai_pattern_score=paragraph_scores["composite_score"],
                detected_patterns=detected,
            )
        )

    passive_ratio_value, passive_examples = PassiveVoiceAnalyzer().score_text(text)
    detected_patterns: list[DetectedPattern] = []
    if section_scores["transition_uniformity"] > 0:
        detected_patterns.append(
            DetectedPattern(
                pattern_type="repetitive_transitions",
                severity=section_scores["transition_uniformity"],
                location=f"section:{section_name}",
                evidence=[
                    sentence
                    for sentence in sentences
                    if any(sentence.lower().startswith(marker) for marker in TRANSITION_MARKERS)
                ][:3],
            )
        )
    if section_scores["lexical_repetition"] > 0.25:
        detected_patterns.append(
            DetectedPattern(
                pattern_type="lexical_repetition",
                severity=section_scores["lexical_repetition"],
                location=f"section:{section_name}",
                evidence=sentences[:3],
            )
        )
    if passive_ratio_value > 0.2:
        detected_patterns.append(
            DetectedPattern(
                pattern_type="passive_voice_overuse",
                severity=min(1.0, passive_ratio_value),
                location=f"section:{section_name}",
                evidence=passive_examples[:3],
            )
        )
    if section_scores["burstiness"] < (config.min_burstiness_to_pass if config else 0.45):
        detected_patterns.append(
            DetectedPattern(
                pattern_type="low_burstiness",
                severity=round(
                    max(0.0, 1.0 - section_scores["burstiness"]),
                    4,
                ),
                location=f"section:{section_name}",
                evidence=sentences[:3],
            )
        )

    paragraph_monotony_score = 0.0
    if len(paragraphs) >= 2:
        paragraph_lengths = [len(_safe_word_tokenize(paragraph)) for paragraph in paragraphs]
        if mean(paragraph_lengths) > 0:
            paragraph_monotony_score = round(
                max(0.0, 1.0 - min(1.0, pstdev(paragraph_lengths) / mean(paragraph_lengths))),
                4,
            )

    active_logger.info(
        "Humanizer detectors for %s: composite=%.3f burstiness=%.3f repetition=%.3f transition=%.3f cadence=%.3f passive=%.3f",
        section_name,
        section_scores["composite_score"],
        section_scores["burstiness"],
        section_scores["lexical_repetition"],
        section_scores["transition_uniformity"],
        section_scores["cadence_uniformity"],
        passive_ratio_value,
    )

    return SectionAnalysis(
        section_name=section_name,
        text=text,
        paragraphs=paragraph_analyses,
        detected_patterns=detected_patterns,
        cadence_score=section_scores["cadence_uniformity"],
        passive_ratio=passive_ratio_value,
        hedge_score=_hedge_ratio(text),
        transition_score=section_scores["transition_uniformity"],
        lexical_repetition_score=section_scores["lexical_repetition"],
        paragraph_monotony_score=paragraph_monotony_score,
        ai_pattern_score=section_scores["composite_score"],
    )


def _hedge_ratio(text: str) -> float:
    sentences = _safe_sent_tokenize(text)
    if not sentences:
        return 0.0
    lowered = (text or "").lower()
    hedge_hits = sum(lowered.count(marker) for marker in HEDGE_MARKERS)
    return round(min(1.0, hedge_hits / len(sentences)), 4)


@lru_cache(maxsize=1)
def _load_spacy_model(model_name: str = "en_core_web_sm"):
    try:
        import spacy
    except ImportError as exc:  # pragma: no cover - dependency dependent
        logger.warning("spaCy is not installed; passive voice detection will use regex only: %s", exc)
        return None

    try:
        return spacy.load(model_name)
    except Exception as exc:  # pragma: no cover - model dependent
        logger.warning(
            "spaCy model '%s' is unavailable; passive voice detection will use regex only: %s",
            model_name,
            exc,
        )
        return None


__all__ = [
    "ParagraphAnalysis",
    "SectionAnalysis",
    "PassiveVoiceAnalyzer",
    "burstiness_score",
    "lexical_repetition_score",
    "transition_uniformity_score",
    "sentence_cadence_score",
    "passive_voice_ratio",
    "composite_ai_score",
    "analyze_section",
]
