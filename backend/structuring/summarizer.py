from __future__ import annotations

import re
from collections import Counter
from statistics import mean
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from core.exceptions import GenerationError
from core.vertex_client import VertexGeminiClient
from structuring.config import StructuringConfig
from structuring.retrieval import SECTION_INTENT_QUERIES, RankedChunk, _tokenize
from structuring.schemas import EvidenceNote, SectionSkeleton, SourceSpan, TextChunk

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")


class SectionReduceResponse(BaseModel):
    draft: str = ""
    key_points: list[str] = Field(default_factory=list)
    direct_evidence: list[str] = Field(default_factory=list)
    inferred_synthesis: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)

    @field_validator(
        "key_points",
        "direct_evidence",
        "inferred_synthesis",
        "missing_evidence",
        mode="before",
    )
    @classmethod
    def normalize_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


class TitleCandidateResponse(BaseModel):
    title_candidates: list[str] = Field(default_factory=list)

    @field_validator("title_candidates", mode="before")
    @classmethod
    def normalize_titles(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


class SectionReducer(Protocol):
    async def reduce_section(
        self,
        *,
        section_name: str,
        notes: list[EvidenceNote],
        context: dict[str, str],
    ) -> SectionReduceResponse:
        ...

    async def suggest_titles(
        self,
        *,
        source_text: str,
        notes: list[EvidenceNote],
        context: dict[str, str],
        limit: int,
    ) -> list[str]:
        ...


class VertexSectionReducer:
    def __init__(
        self,
        *,
        client: VertexGeminiClient,
        model_name: str | None = None,
    ):
        self.client = client
        self.model_name = model_name

    async def reduce_section(
        self,
        *,
        section_name: str,
        notes: list[EvidenceNote],
        context: dict[str, str],
    ) -> SectionReduceResponse:
        notes_json = "[\n" + ",\n".join(note.model_dump_json(indent=2) for note in notes) + "\n]"
        prompt = (
            "You are the Structuring Agent reducer for an IEEE paper pipeline.\n"
            "Convert the evidence notes into a grounded skeletal section.\n"
            "Return concise JSON only.\n"
            "Do not produce polished prose; keep it evidence-oriented and downstream-friendly.\n"
            "Separate direct evidence from inferred synthesis and explicitly call out missing evidence.\n\n"
            f"Section: {section_name}\n"
            f"Section intent: {SECTION_INTENT_QUERIES.get(section_name, section_name)}\n"
            f"Paper topic: {context.get('paper_topic', '')}\n"
            f"Paper domain: {context.get('paper_domain', '')}\n\n"
            f"Evidence notes:\n{notes_json}"
        )
        return await self.client.generate_json(
            prompt=prompt,
            response_schema=SectionReduceResponse,
            model_name=self.model_name,
        )

    async def suggest_titles(
        self,
        *,
        source_text: str,
        notes: list[EvidenceNote],
        context: dict[str, str],
        limit: int,
    ) -> list[str]:
        note_lines = [f"- {note.note}" for note in notes[:limit]]
        prompt = (
            "You generate concise IEEE-style research paper title candidates.\n"
            "Return JSON only with title_candidates as a short list of clear, academically plausible titles.\n"
            "Keep the titles faithful to the evidence and avoid hype.\n"
            f"Limit: {limit}\n"
            f"Paper topic: {context.get('paper_topic', '')}\n"
            f"Paper domain: {context.get('paper_domain', '')}\n"
            f"Evidence summary:\n{chr(10).join(note_lines) or source_text[:500]}"
        )
        response = await self.client.generate_json(
            prompt=prompt,
            response_schema=TitleCandidateResponse,
            model_name=self.model_name,
        )
        return response.title_candidates[:limit]


def map_chunks_to_evidence_notes(
    *,
    section_name: str,
    ranked_chunks: list[RankedChunk],
    config: StructuringConfig,
) -> list[EvidenceNote]:
    section_terms = _tokenize(SECTION_INTENT_QUERIES.get(section_name, section_name))
    notes: list[EvidenceNote] = []
    for ranked in ranked_chunks:
        sentences = _select_relevant_sentences(ranked.chunk, section_terms, config)
        if not sentences:
            continue
        quote = " ".join(sentences[:1])[: config.quote_max_chars].strip()
        notes.append(
            EvidenceNote(
                section_name=section_name,
                chunk_id=ranked.chunk.chunk_id,
                note=" ".join(sentences[:2]).strip(),
                direct_evidence=sentences[:2],
                inferred_synthesis=_infer_from_sentences(section_name, sentences),
                missing_information=_missing_section_signals(section_name, " ".join(sentences)),
                source_spans=[
                    SourceSpan(
                        chunk_id=ranked.chunk.chunk_id,
                        start_char=ranked.chunk.start_char,
                        end_char=ranked.chunk.end_char,
                        quote=quote or None,
                        relevance_score=round(ranked.relevance_score, 4),
                    )
                ],
                relevance_score=round(ranked.relevance_score, 4),
            )
        )
    return notes


async def build_section_skeleton(
    *,
    section_name: str,
    notes: list[EvidenceNote],
    ranked_chunks: list[RankedChunk],
    reducer: SectionReducer | None,
    context: dict[str, str],
    config: StructuringConfig,
) -> SectionSkeleton:
    fallback = deterministic_reduce_section(
        section_name=section_name,
        notes=notes,
        ranked_chunks=ranked_chunks,
        config=config,
    )
    reduced = fallback
    if reducer is not None and notes:
        try:
            llm_result = await reducer.reduce_section(
                section_name=section_name,
                notes=notes,
                context=context,
            )
            reduced = _merge_reduction_outputs(section_name=section_name, llm_result=llm_result, fallback=fallback)
        except Exception as exc:
            if isinstance(exc, GenerationError):
                pass

    confidence = compute_section_confidence(
        section_name=section_name,
        notes=notes,
        ranked_chunks=ranked_chunks,
        skeleton=reduced,
        config=config,
    )
    reduced.confidence = confidence
    return reduced


def deterministic_reduce_section(
    *,
    section_name: str,
    notes: list[EvidenceNote],
    ranked_chunks: list[RankedChunk],
    config: StructuringConfig,
) -> SectionSkeleton:
    if not notes:
        return SectionSkeleton(
            section_name=section_name,
            draft=f"No reliable evidence was retrieved for the {section_name.replace('_', ' ')} section.",
            key_points=[],
            source_spans=[],
            missing_evidence=[f"No grounded evidence was available for {section_name.replace('_', ' ')}."],
            direct_evidence=[],
            inferred_synthesis=[],
        )

    direct_evidence = _deduplicate_strings(
        item
        for note in notes
        for item in note.direct_evidence
    )[: config.max_key_points]
    inferred_synthesis = _deduplicate_strings(
        item
        for note in notes
        for item in note.inferred_synthesis
    )[: max(1, config.max_key_points - 1)]
    missing_evidence = _deduplicate_strings(
        item
        for note in notes
        for item in note.missing_information
    )[: config.max_key_points]
    key_points = _deduplicate_strings(
        [note.note for note in notes if note.note] + direct_evidence
    )[: config.max_key_points]
    source_spans = _deduplicate_source_spans(notes)

    draft = " ".join(direct_evidence[:2]).strip() or " ".join(note.note for note in notes[:2]).strip()
    if inferred_synthesis:
        draft = f"{draft} {inferred_synthesis[0]}".strip()

    return SectionSkeleton(
        section_name=section_name,
        draft=draft,
        key_points=key_points,
        source_spans=source_spans,
        missing_evidence=missing_evidence,
        direct_evidence=direct_evidence,
        inferred_synthesis=inferred_synthesis,
    )


def compute_section_confidence(
    *,
    section_name: str,
    notes: list[EvidenceNote],
    ranked_chunks: list[RankedChunk],
    skeleton: SectionSkeleton,
    config: StructuringConfig,
) -> float:
    if not ranked_chunks or not notes:
        return 0.05

    retrieval_count_score = min(len(ranked_chunks) / max(config.top_k_per_section, 1), 1.0)
    average_relevance = mean(item.relevance_score for item in ranked_chunks[: config.top_k_per_section])
    signal_terms = set(_tokenize(SECTION_INTENT_QUERIES.get(section_name, section_name)))
    observed_terms = set(_tokenize(" ".join(note.note for note in notes)))
    signal_coverage = len(signal_terms & observed_terms) / max(len(signal_terms), 1)
    consistency = _note_consistency(notes)
    missing_penalty = min(len(skeleton.missing_evidence), 4) * 0.08

    confidence = (
        retrieval_count_score * 0.25
        + average_relevance * 0.35
        + signal_coverage * 0.25
        + consistency * 0.15
        - missing_penalty
    )
    return round(max(0.0, min(1.0, confidence)), 4)


async def build_title_candidates(
    *,
    source_text: str,
    title_notes: list[EvidenceNote],
    reducer: SectionReducer | None,
    context: dict[str, str],
    config: StructuringConfig,
) -> list[str]:
    if reducer is not None and title_notes:
        try:
            suggestions = await reducer.suggest_titles(
                source_text=source_text,
                notes=title_notes,
                context=context,
                limit=config.title_candidate_limit,
            )
            normalized = _deduplicate_strings(suggestions)
            if normalized:
                return normalized[: config.title_candidate_limit]
        except Exception:
            pass
    return deterministic_title_candidates(
        source_text=source_text,
        title_notes=title_notes,
        context=context,
        config=config,
    )


def deterministic_title_candidates(
    *,
    source_text: str,
    title_notes: list[EvidenceNote],
    context: dict[str, str],
    config: StructuringConfig,
) -> list[str]:
    candidates: list[str] = []
    topic = context.get("paper_topic", "").strip()
    domain = context.get("paper_domain", "").strip()
    if topic:
        candidates.append(topic)
        if domain:
            candidates.append(f"{topic}: An {domain} Study")
    note_terms = Counter(
        token
        for note in title_notes
        for token in _tokenize(note.note)
        if len(token) > 3
    )
    common_terms = [term.title() for term, _ in note_terms.most_common(4)]
    if common_terms:
        candidates.append(" ".join(common_terms[:4]))
    first_sentence = _split_sentences(source_text[:400])[0:1]
    if first_sentence:
        candidates.append(first_sentence[0][:80].strip(" ."))
    normalized = _deduplicate_strings(candidate for candidate in candidates if candidate)
    return normalized[: config.title_candidate_limit] or ["Structured Research Paper Draft"]


def extract_keywords(
    *,
    source_text: str,
    section_summaries: dict[str, SectionSkeleton],
    context: dict[str, str],
    limit: int = 5,
) -> list[str]:
    candidates = " ".join(
        [
            source_text[:1200],
            context.get("paper_topic", ""),
            context.get("paper_domain", ""),
            *[section.draft for section in section_summaries.values()],
        ]
    )
    counter = Counter(token for token in _tokenize(candidates) if len(token) > 3)
    keywords = [term for term, _ in counter.most_common(limit)]
    domain = context.get("paper_domain", "").strip()
    if domain and domain.casefold() not in {keyword.casefold() for keyword in keywords}:
        keywords.insert(0, domain)
    cleaned = [keyword.strip() for keyword in keywords if keyword.strip()]
    return cleaned[:limit] or ["research generation"]


def _merge_reduction_outputs(
    *,
    section_name: str,
    llm_result: SectionReduceResponse,
    fallback: SectionSkeleton,
) -> SectionSkeleton:
    draft = llm_result.draft.strip() or fallback.draft
    key_points = _deduplicate_strings(llm_result.key_points or fallback.key_points)
    direct_evidence = _deduplicate_strings(llm_result.direct_evidence or fallback.direct_evidence)
    inferred_synthesis = _deduplicate_strings(llm_result.inferred_synthesis or fallback.inferred_synthesis)
    missing_evidence = _deduplicate_strings(llm_result.missing_evidence or fallback.missing_evidence)
    return SectionSkeleton(
        section_name=section_name,
        draft=draft,
        key_points=key_points,
        source_spans=fallback.source_spans,
        missing_evidence=missing_evidence,
        direct_evidence=direct_evidence,
        inferred_synthesis=inferred_synthesis,
    )


def _select_relevant_sentences(
    chunk: TextChunk,
    section_terms: list[str],
    config: StructuringConfig,
) -> list[str]:
    sentences = _split_sentences(chunk.text)
    if not sentences:
        return []

    scored_sentences = [
        (sentence, _sentence_score(sentence, section_terms))
        for sentence in sentences
    ]
    scored_sentences.sort(key=lambda item: item[1], reverse=True)
    selected = [sentence.strip() for sentence, _ in scored_sentences[:2] if sentence.strip()]
    if not selected:
        selected = [chunk.text[: config.quote_max_chars].strip()]
    return selected


def _split_sentences(text: str) -> list[str]:
    normalized = text.replace("\n", " ").strip()
    if not normalized:
        return []
    return [segment.strip() for segment in SENTENCE_PATTERN.split(normalized) if segment.strip()]


def _sentence_score(sentence: str, section_terms: list[str]) -> float:
    sentence_terms = set(_tokenize(sentence))
    if not sentence_terms:
        return 0.0
    overlap = len(sentence_terms & set(section_terms))
    return overlap / max(len(section_terms), 1)


def _infer_from_sentences(section_name: str, sentences: list[str]) -> list[str]:
    if not sentences:
        return []
    joined = " ".join(sentences).lower()
    if section_name == "methodology" and any(term in joined for term in ("method", "approach", "pipeline", "algorithm")):
        return ["The retrieved evidence indicates the core workflow or experimental procedure used in the study."]
    if section_name == "results" and any(term in joined for term in ("result", "accuracy", "performance", "metric", "finding")):
        return ["The evidence supports a concise results summary grounded in reported findings or evaluation signals."]
    if section_name == "limitations":
        return ["The available evidence suggests explicit or implicit constraints that should be surfaced for downstream drafting."]
    return [f"The retrieved evidence contributes to the {section_name.replace('_', ' ')} narrative."]


def _missing_section_signals(section_name: str, text: str) -> list[str]:
    text_terms = set(_tokenize(text))
    expected_terms = set(_tokenize(SECTION_INTENT_QUERIES.get(section_name, section_name)))
    missing = [term for term in expected_terms if term not in text_terms]
    if not missing:
        return []
    friendly_labels = {
        "methodology": "Detailed procedure or experimental setup evidence is limited.",
        "results": "Quantitative findings or evaluation metrics are not clearly supported.",
        "discussion": "Interpretation or implication details are limited in the retrieved evidence.",
        "limitations": "Explicit limitation statements are sparse in the available evidence.",
    }
    if section_name in friendly_labels:
        return [friendly_labels[section_name]]
    return [f"Some expected {section_name.replace('_', ' ')} signals are missing from the retrieved evidence."]


def _note_consistency(notes: list[EvidenceNote]) -> float:
    if len(notes) <= 1:
        return 0.8 if notes else 0.0
    token_sets = [set(_tokenize(note.note)) for note in notes if note.note]
    if len(token_sets) <= 1:
        return 0.4
    overlaps: list[float] = []
    for index in range(len(token_sets)):
        for other_index in range(index + 1, len(token_sets)):
            left = token_sets[index]
            right = token_sets[other_index]
            if not left or not right:
                continue
            overlaps.append(len(left & right) / max(len(left | right), 1))
    return mean(overlaps) if overlaps else 0.2


def _deduplicate_source_spans(notes: list[EvidenceNote]) -> list[SourceSpan]:
    seen: set[tuple[str, int, int]] = set()
    unique_spans: list[SourceSpan] = []
    for note in notes:
        for span in note.source_spans:
            key = (span.chunk_id, span.start_char, span.end_char)
            if key in seen:
                continue
            seen.add(key)
            unique_spans.append(span)
    return unique_spans


def _deduplicate_strings(values) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(cleaned)
    return deduplicated
