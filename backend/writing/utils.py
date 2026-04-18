from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from statistics import mean
from typing import Iterable

from structuring.schemas import SectionSkeleton, SourceSpan, StructuredPaperDraft
from writing.schemas import WrittenClaim

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
HEDGING_MARKERS = (
    "suggests",
    "appears",
    "may",
    "might",
    "could",
    "likely",
    "approximately",
    "tentative",
    "limited evidence",
    "indicates",
)
INFERENCE_MARKERS = (
    "suggests",
    "may indicate",
    "could reflect",
    "implies",
    "appears to",
    "is consistent with",
)
ASSERTIVE_MARKERS = (
    "shows",
    "demonstrates",
    "proves",
    "establishes",
    "confirms",
)


@dataclass(frozen=True)
class ConfidencePhraseProfile:
    label: str
    guidance: str
    evidence_lead: str
    inference_lead: str
    limitation_lead: str


@dataclass(frozen=True)
class AnnotationBundle:
    claims: list[WrittenClaim]
    evidence_backed_sentences: list[str]
    inferred_sentences: list[str]
    hedged_sentences: list[str]
    unsupported_sentences: list[str]
    used_source_spans: list[dict[str, object]]


def confidence_profile(
    confidence: float,
    *,
    low_threshold: float,
    medium_threshold: float,
    high_threshold: float,
) -> ConfidencePhraseProfile:
    if confidence >= high_threshold:
        return ConfidencePhraseProfile(
            label="high",
            guidance="Use direct but still formal academic prose.",
            evidence_lead="The evidence shows",
            inference_lead="These findings indicate",
            limitation_lead="A bounded limitation is",
        )
    if confidence >= medium_threshold:
        return ConfidencePhraseProfile(
            label="medium",
            guidance="Use measured certainty and avoid overstatement.",
            evidence_lead="The available evidence suggests",
            inference_lead="The material indicates",
            limitation_lead="One practical limitation is",
        )
    if confidence >= low_threshold:
        return ConfidencePhraseProfile(
            label="low",
            guidance="Use explicit hedging and narrower claims.",
            evidence_lead="The available evidence appears to indicate",
            inference_lead="A tentative interpretation is",
            limitation_lead="The source material provides limited support for",
        )
    return ConfidencePhraseProfile(
        label="very_low",
        guidance="Avoid strong prose and explicitly signal limited support.",
        evidence_lead="The source material provides only limited support for",
        inference_lead="Any interpretation remains tentative",
        limitation_lead="The limited evidence highlights",
    )


def split_sentences(text: str) -> list[str]:
    normalized = text.replace("\n", " ").strip()
    if not normalized:
        return []
    return [segment.strip() for segment in SENTENCE_PATTERN.split(normalized) if segment.strip()]


def build_source_span_id(span: SourceSpan) -> str:
    return f"{span.chunk_id}:{span.start_char}:{span.end_char}"


def serialize_source_spans(spans: Iterable[SourceSpan]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    seen: set[str] = set()
    for span in spans:
        span_id = build_source_span_id(span)
        if span_id in seen:
            continue
        seen.add(span_id)
        serialized.append(
            {
                "span_id": span_id,
                "chunk_id": span.chunk_id,
                "start_char": span.start_char,
                "end_char": span.end_char,
                "quote": span.quote,
                "relevance_score": span.relevance_score,
            }
        )
    return serialized


def annotate_section_text(
    *,
    text: str,
    section_name: str,
    confidence: float,
    skeleton: SectionSkeleton,
) -> AnnotationBundle:
    sentences = split_sentences(text)
    direct_markers = {normalize_sentence(sentence) for sentence in skeleton.direct_evidence}
    inferred_markers = {normalize_sentence(sentence) for sentence in skeleton.inferred_synthesis}
    used_source_spans = serialize_source_spans(skeleton.source_spans)
    span_ids = [record["span_id"] for record in used_source_spans]

    claims: list[WrittenClaim] = []
    evidence_backed_sentences: list[str] = []
    inferred_sentences: list[str] = []
    hedged_sentences: list[str] = []
    unsupported_sentences: list[str] = []

    for sentence in sentences:
        normalized = normalize_sentence(sentence)
        evidence_backed = _matches_support(normalized, direct_markers) or _sentence_token_overlap(sentence, skeleton.direct_evidence) >= 0.45
        inferred = _matches_support(normalized, inferred_markers) or any(marker in normalized for marker in INFERENCE_MARKERS)
        hedged = any(marker in normalized for marker in HEDGING_MARKERS)
        unsupported = _looks_assertive(normalized) and not evidence_backed and not hedged and not inferred and not span_ids

        if evidence_backed:
            evidence_backed_sentences.append(sentence)
        if inferred:
            inferred_sentences.append(sentence)
        if hedged:
            hedged_sentences.append(sentence)
        if unsupported:
            unsupported_sentences.append(sentence)

        claim_type = "evidence" if evidence_backed else "inference" if inferred else "context"
        claims.append(
            WrittenClaim(
                text=sentence,
                claim_type=claim_type,
                confidence=confidence if not unsupported else min(confidence, 0.35),
                source_span_ids=span_ids if evidence_backed or inferred else [],
                is_inferred=inferred,
                is_hedged=hedged,
            )
        )

    return AnnotationBundle(
        claims=claims,
        evidence_backed_sentences=evidence_backed_sentences,
        inferred_sentences=inferred_sentences,
        hedged_sentences=hedged_sentences,
        unsupported_sentences=unsupported_sentences,
        used_source_spans=used_source_spans,
    )


def score_title_candidate(
    candidate: str,
    *,
    structured_draft: StructuredPaperDraft,
    paper_topic: str,
    paper_domain: str,
    max_words: int,
) -> float:
    normalized = candidate.strip()
    if not normalized:
        return -1.0

    words = normalized.split()
    length_score = 1.0 if len(words) <= max_words else max(0.2, 1.0 - ((len(words) - max_words) * 0.1))
    topic_tokens = set(tokenize(paper_topic))
    domain_tokens = set(tokenize(paper_domain))
    draft_tokens = set(tokenize(" ".join(section.draft for section in structured_draft.sections.values())))
    candidate_tokens = set(tokenize(normalized))
    alignment = 0.0
    if candidate_tokens:
        alignment += len(candidate_tokens & draft_tokens) / len(candidate_tokens)
        if topic_tokens:
            alignment += len(candidate_tokens & topic_tokens) / max(len(topic_tokens), 1)
        if domain_tokens:
            alignment += len(candidate_tokens & domain_tokens) / max(len(domain_tokens), 1)
    specificity = min(len(candidate_tokens) / 8, 1.0)
    generic_penalty = 0.3 if {"study", "paper", "approach"} <= candidate_tokens else 0.0
    return round((length_score * 0.35) + (alignment * 0.45) + (specificity * 0.2) - generic_penalty, 4)


def derive_keywords(
    *,
    title: str,
    abstract_text: str,
    section_texts: Iterable[str],
    paper_domain: str,
    fallback_keywords: list[str] | None = None,
    limit: int = 5,
) -> list[str]:
    if fallback_keywords:
        normalized = [keyword.strip() for keyword in fallback_keywords if keyword.strip()]
        if normalized:
            return normalized[:limit]

    corpus = " ".join([title, abstract_text, paper_domain, *section_texts])
    counter = Counter(token for token in tokenize(corpus) if len(token) > 3)
    keywords = [term for term, _ in counter.most_common(limit)]
    if paper_domain:
        domain_value = paper_domain.strip()
        if domain_value and domain_value.casefold() not in {keyword.casefold() for keyword in keywords}:
            keywords.insert(0, domain_value)
    return [keyword.strip() for keyword in keywords if keyword.strip()][:limit] or ["research generation"]


def compute_global_confidence(section_confidences: Iterable[float]) -> float:
    values = list(section_confidences)
    if not values:
        return 0.0
    return round(mean(values), 4)


def summarize_annotations(*, abstract_bundle: AnnotationBundle, section_bundles: dict[str, AnnotationBundle]) -> dict[str, int]:
    bundles = [abstract_bundle, *section_bundles.values()]
    return {
        "claims": sum(len(bundle.claims) for bundle in bundles),
        "evidence_backed_sentences": sum(len(bundle.evidence_backed_sentences) for bundle in bundles),
        "inferred_sentences": sum(len(bundle.inferred_sentences) for bundle in bundles),
        "hedged_sentences": sum(len(bundle.hedged_sentences) for bundle in bundles),
        "unsupported_sentences": sum(len(bundle.unsupported_sentences) for bundle in bundles),
        "used_source_spans": sum(len(bundle.used_source_spans) for bundle in bundles),
    }


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def normalize_sentence(sentence: str) -> str:
    return " ".join(tokenize(sentence))


def _sentence_token_overlap(sentence: str, candidates: list[str]) -> float:
    sentence_tokens = set(tokenize(sentence))
    if not sentence_tokens:
        return 0.0
    best = 0.0
    for candidate in candidates:
        candidate_tokens = set(tokenize(candidate))
        if not candidate_tokens:
            continue
        overlap = len(sentence_tokens & candidate_tokens) / max(len(sentence_tokens | candidate_tokens), 1)
        if overlap > best:
            best = overlap
    return best


def _matches_support(normalized_sentence: str, support_markers: set[str]) -> bool:
    if normalized_sentence in support_markers:
        return True
    return any(marker and marker in normalized_sentence for marker in support_markers)


def _looks_assertive(normalized_sentence: str) -> bool:
    return any(marker in normalized_sentence for marker in ASSERTIVE_MARKERS)
