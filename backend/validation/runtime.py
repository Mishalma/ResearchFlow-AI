from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from statistics import mean

from core.config import Settings, get_settings
from humanizer.detectors import composite_ai_score
from humanizer.perplexity import PerplexityScorer
from jobs.artifacts import (
    load_extracted_text_artifact,
    load_generated_draft_artifact,
    load_validation_report_from_artifact,
    store_validation_report_artifact,
)
from models.generation import GeneratedPaper
from models.validation import (
    ValidationReport,
    ValidationSectionFlag,
    ValidationSectionReport,
    ValidationServiceRequest,
    ValidationServiceResponse,
)
from originality.classifier import classify_section_findings
from originality.config import OriginalityConfig
from originality.schemas import ProviderFinding, ProviderSectionScan
from originality.utils import SECTION_ORDER, build_section_map, summarize_status_counts
from validation.config import ValidationConfig
from validation.stylometry import iter_sentence_spans, stylometry_profile, tokenize_words

logger = logging.getLogger("papereasy.validation.runtime")

_STRIP_CITATIONS_PATTERN = re.compile(r"\[[0-9,\-\s]+\]|\\cite[t|p]?\{[^}]+\}")
_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class _SourceSentence:
    index: int
    text: str
    normalized: str
    tokens: tuple[str, ...]
    ngrams: tuple[tuple[str, ...], ...]


def _normalize_for_overlap(text: str) -> str:
    lowered = _STRIP_CITATIONS_PATTERN.sub(" ", text or "").lower()
    lowered = _NORMALIZE_PATTERN.sub(" ", lowered)
    return _WHITESPACE_PATTERN.sub(" ", lowered).strip()


def _build_ngrams(tokens: list[str] | tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    if len(tokens) < size:
        return ()
    return tuple(tuple(tokens[index : index + size]) for index in range(0, len(tokens) - size + 1))


def _merge_span_lengths(spans: list[tuple[int, int]]) -> int:
    if not spans:
        return 0
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(max(0, end - start) for start, end in merged)


def _confidence_band(routing_decision: str) -> str:
    if routing_decision == "flagged":
        return "high"
    if routing_decision == "borderline":
        return "medium"
    if routing_decision == "clean":
        return "low"
    return "unknown"


def _decision_summary(routing_decision: str) -> str:
    if routing_decision == "clean":
        return "The manuscript cleared the fast AI and overlap validation checks."
    if routing_decision == "borderline":
        return "The manuscript requires manual review because fast validation found moderate AI or overlap risk."
    if routing_decision == "flagged":
        return "The manuscript requires manual review because fast validation found high AI or overlap risk."
    return "Validation is pending."


def _draft_revision_from_uri(uri: str) -> str:
    match = re.search(r"draft_v(\d+)\.json$", str(uri or ""))
    if not match:
        return "v1"
    return f"v{match.group(1)}"


def _section_status(spans: list, *, ai_score: float | None, plagiarism_score: float, config: ValidationConfig) -> tuple[str, str, list[str]]:
    classifications = {span.classification for span in spans}
    severe = (
        "likely_unattributed_copying" in classifications
        or (ai_score is not None and ai_score >= config.ai_flag_threshold)
        or plagiarism_score > config.plagiarism_flag_threshold
    )
    medium = (
        severe
        or bool(classifications & {"possible_self_overlap", "manual_review_required", "uncited_close_paraphrase"})
        or (ai_score is not None and ai_score >= config.ai_clean_threshold)
        or plagiarism_score >= config.plagiarism_clean_threshold
    )

    if severe:
        return (
            "blocked",
            "severe",
            ["High-risk AI or unattributed overlap signals were detected in this section."],
        )
    if medium:
        return (
            "needs_manual_review",
            "medium",
            ["This section contains moderate AI or overlap signals and should be reviewed manually."],
        )
    if spans:
        return (
            "clean_with_notes",
            "low",
            ["Only low-risk or citation-safe overlap was detected in this section."],
        )
    return ("clean", "low", ["No blocking AI or overlap signals were detected in this section."])


def _routing_decision_for_report(
    *,
    ai_score: float | None,
    plagiarism_score: float,
    section_flags: list[ValidationSectionFlag],
    config: ValidationConfig,
) -> str:
    severe_section_flag = any(flag.risk == "severe" for flag in section_flags)
    medium_section_flag = any(flag.risk == "medium" for flag in section_flags)

    if (
        (ai_score is not None and ai_score >= config.ai_flag_threshold)
        or plagiarism_score > config.plagiarism_flag_threshold
        or severe_section_flag
    ):
        return "flagged"
    if (
        (ai_score is not None and ai_score >= config.ai_clean_threshold)
        or plagiarism_score >= config.plagiarism_clean_threshold
        or medium_section_flag
    ):
        return "borderline"
    return "clean"


def _build_source_index(source_text: str, *, ngram_size: int, min_tokens: int) -> tuple[list[_SourceSentence], dict[tuple[str, ...], set[int]]]:
    sentences: list[_SourceSentence] = []
    index: dict[tuple[str, ...], set[int]] = {}
    for _start, _end, sentence_text in iter_sentence_spans(source_text):
        normalized = _normalize_for_overlap(sentence_text)
        tokens = tuple(tokenize_words(normalized))
        if len(tokens) < min_tokens:
            continue
        ngrams = _build_ngrams(tokens, ngram_size)
        if not ngrams:
            continue
        sentence_index = len(sentences)
        entry = _SourceSentence(
            index=sentence_index,
            text=sentence_text,
            normalized=normalized,
            tokens=tokens,
            ngrams=ngrams,
        )
        sentences.append(entry)
        for ngram in set(ngrams):
            index.setdefault(ngram, set()).add(sentence_index)
    return sentences, index


def _detect_section_overlap(
    *,
    section_name: str,
    section_text: str,
    source_sentences: list[_SourceSentence],
    source_index: dict[tuple[str, ...], set[int]],
    project_id: str,
    config: ValidationConfig,
) -> ProviderSectionScan:
    findings: list[ProviderFinding] = []
    sentence_spans = iter_sentence_spans(section_text)
    if not sentence_spans:
        return ProviderSectionScan(
            provider_name=config.provider_name,
            section_name=section_name,
            originality_score=1.0,
            ai_score=None,
            spans=[],
            raw_payload={},
            metadata={"provider_summary": {config.provider_name: 1}},
        )

    for start_char, end_char, sentence_text in sentence_spans:
        normalized = _normalize_for_overlap(sentence_text)
        tokens = tokenize_words(normalized)
        if len(tokens) < config.overlap_sentence_min_tokens:
            continue

        ngrams = _build_ngrams(tokens, config.overlap_ngram_size)
        if not ngrams:
            continue

        candidate_counts: dict[int, int] = {}
        for ngram in set(ngrams):
            for candidate_index in source_index.get(ngram, set()):
                candidate_counts[candidate_index] = candidate_counts.get(candidate_index, 0) + 1
        if not candidate_counts:
            continue

        best_candidate: _SourceSentence | None = None
        best_similarity = 0.0
        best_overlap_ratio = 0.0
        for candidate_index, overlap_count in sorted(
            candidate_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:12]:
            candidate = source_sentences[candidate_index]
            overlap_ratio = overlap_count / max(1, len(set(ngrams)))
            sequence_ratio = SequenceMatcher(None, normalized, candidate.normalized).ratio()
            similarity = max(overlap_ratio, sequence_ratio)
            if similarity > best_similarity:
                best_similarity = similarity
                best_overlap_ratio = overlap_ratio
                best_candidate = candidate

        if best_candidate is None:
            continue

        if best_overlap_ratio < config.overlap_ratio_threshold and best_similarity < config.sequence_ratio_threshold:
            continue

        severity = round(min(1.0, max(best_similarity, 0.35 + (best_overlap_ratio * 0.65))), 4)
        findings.append(
            ProviderFinding(
                start_char=start_char,
                end_char=end_char,
                matched_text=sentence_text,
                similarity_score=round(best_similarity, 4),
                matched_source_title="Uploaded source document",
                matched_source_url=f"project-source://{project_id}",
                severity=severity,
                metadata={
                    "provider_name": config.provider_name,
                    "source_sentence_preview": best_candidate.text[:220],
                    "overlap_ratio": round(best_overlap_ratio, 4),
                },
            )
        )

    suspicious_characters = _merge_span_lengths([(item.start_char, item.end_char) for item in findings])
    section_length = max(1, len(section_text.strip()))
    originality_score = round(max(0.0, 1.0 - (suspicious_characters / section_length)), 4)

    return ProviderSectionScan(
        provider_name=config.provider_name,
        section_name=section_name,
        originality_score=originality_score,
        ai_score=None,
        spans=findings,
        raw_payload={"finding_count": len(findings)},
        metadata={
            "provider_summary": {config.provider_name: 1},
            "sentence_count": len(sentence_spans),
        },
    )


def _suspicious_spans_for_section(section_report: ValidationSectionReport) -> list[tuple[int, int]]:
    return [
        (span.start_char, span.end_char)
        for span in section_report.spans
        if span.classification not in {"quoted_and_cited", "common_phrase", "boilerplate"}
    ]


def _build_section_flags_from_reports(
    *,
    section_reports: list[ValidationSectionReport],
    config: ValidationConfig,
) -> list[ValidationSectionFlag]:
    section_flags: list[ValidationSectionFlag] = []
    for section in section_reports:
        if section.ai_score is not None and section.ai_score >= config.ai_clean_threshold:
            section_flags.append(
                ValidationSectionFlag(
                    section_id=section.section_name,
                    flag_type="ai",
                    score=round(section.ai_score, 4),
                    risk="severe" if section.ai_score >= config.ai_flag_threshold else "medium",
                    summary=f"{section.section_name.replace('_', ' ').title()} shows elevated AI-style signals.",
                )
            )
        suspicious_spans = _suspicious_spans_for_section(section)
        if suspicious_spans and section.plagiarism_score >= config.plagiarism_clean_threshold:
            section_flags.append(
                ValidationSectionFlag(
                    section_id=section.section_name,
                    flag_type="plagiarism",
                    score=section.plagiarism_score,
                    risk="severe"
                    if section.plagiarism_score > config.plagiarism_flag_threshold
                    else "medium",
                    summary=f"{section.section_name.replace('_', ' ').title()} contains lexical overlap with the uploaded source.",
                )
            )
    return section_flags


@lru_cache(maxsize=1)
def _get_perplexity_scorer(model_name: str) -> PerplexityScorer:
    return PerplexityScorer(model_name)


def _perplexity_risk(text: str, *, config: ValidationConfig) -> tuple[float | None, float | None]:
    scorer = _get_perplexity_scorer(config.perplexity_model_name)
    value = scorer.score(text)
    if value is None:
        return None, None
    if value >= 45.0:
        return value, 0.05
    if value <= 20.0:
        return value, 0.95
    normalized = 1.0 - ((value - 20.0) / 25.0)
    return value, round(max(0.0, min(1.0, normalized)), 4)


def _ai_score_for_section(text: str, *, config: ValidationConfig) -> tuple[float | None, dict[str, float]]:
    if not text.strip():
        return None, {}

    detector_scores = composite_ai_score(text)
    stylometry_scores = stylometry_profile(text)
    _, perplexity_risk = _perplexity_risk(text, config=config)
    perplexity_component = 0.0 if perplexity_risk is None else perplexity_risk
    raw_score = (
        (detector_scores.get("composite_score", 0.0) * config.detector_weight)
        + (stylometry_scores.get("score", 0.0) * config.stylometry_weight)
        + (perplexity_component * config.perplexity_weight)
    )
    score = round(max(0.0, min(1.0, raw_score)), 4)
    return score, {
        **detector_scores,
        "stylometry_score": stylometry_scores.get("score", 0.0),
        "type_token_ratio": stylometry_scores.get("type_token_ratio", 0.0),
        "sentence_length_variance": stylometry_scores.get("sentence_length_variance", 0.0),
        "paragraph_monotony": stylometry_scores.get("paragraph_monotony", 0.0),
        "perplexity_risk": perplexity_component,
    }


def _build_section_report(
    *,
    section_name: str,
    section_text: str,
    source_sentences: list[_SourceSentence],
    source_index: dict[tuple[str, ...], set[int]],
    request: ValidationServiceRequest,
    validation_config: ValidationConfig,
    originality_config: OriginalityConfig,
    reference_lines: list[str],
) -> ValidationSectionReport:
    section_ai_score, ai_metadata = _ai_score_for_section(
        section_text,
        config=validation_config,
    )
    scan = _detect_section_overlap(
        section_name=section_name,
        section_text=section_text,
        source_sentences=source_sentences,
        source_index=source_index,
        project_id=request.project_id,
        config=validation_config,
    )
    classified_spans = classify_section_findings(
        section_name=section_name,
        section_text=section_text,
        findings=scan.spans,
        reference_lines=reference_lines,
        author_metadata=None,
        config=originality_config,
    )

    suspicious_spans = [
        (span.start_char, span.end_char)
        for span in classified_spans
        if span.classification not in {"quoted_and_cited", "common_phrase", "boilerplate"}
    ]
    section_length = max(1, len(section_text))
    plagiarism_score = round((_merge_span_lengths(suspicious_spans) / section_length) * 100, 2)
    status, risk, summary = _section_status(
        classified_spans,
        ai_score=section_ai_score,
        plagiarism_score=plagiarism_score,
        config=validation_config,
    )

    metadata_summary: list[str] = []
    if ai_metadata:
        metadata_summary.append(
            f"AI composite {ai_metadata.get('composite_score', 0.0):.2f}; stylometry {ai_metadata.get('stylometry_score', 0.0):.2f}"
        )

    return ValidationSectionReport(
        section_name=section_name,
        ai_score=section_ai_score,
        plagiarism_score=plagiarism_score,
        status=status,
        risk=risk,
        summary=summary + metadata_summary,
        spans=classified_spans,
    )


async def execute_fast_validation(
    request: ValidationServiceRequest,
    *,
    settings: Settings | None = None,
    validation_config: ValidationConfig | None = None,
    originality_config: OriginalityConfig | None = None,
) -> ValidationServiceResponse:
    resolved_settings = settings or get_settings()
    resolved_validation_config = validation_config or ValidationConfig.from_settings(resolved_settings)
    resolved_originality_config = originality_config or OriginalityConfig.from_settings(resolved_settings)

    draft = load_generated_draft_artifact(request.current_draft_uri)
    extracted_text_uri = request.artifacts.extracted_text_uri
    if not extracted_text_uri:
        raise ValueError("Validation requests require artifacts.extracted_text_uri.")
    source_text = load_extracted_text_artifact(extracted_text_uri)

    section_texts = build_section_map(humanized_draft=None, paper_snapshot=draft)
    source_sentences, source_index = _build_source_index(
        source_text,
        ngram_size=resolved_validation_config.overlap_ngram_size,
        min_tokens=resolved_validation_config.overlap_sentence_min_tokens,
    )

    reference_lines = list(draft.paper.references)
    requested_changed_sections = set(request.config.changed_section_ids)
    if request.config.changed_sections_only and not requested_changed_sections:
        raise ValueError("changed_section_ids is required when changed_sections_only=true.")

    previous_report = None
    previous_report_uri = request.artifacts.previous_validation_report_uri
    if request.config.changed_sections_only:
        if not previous_report_uri:
            raise ValueError(
                "previous_validation_report_uri is required when changed_sections_only=true."
            )
        previous_report = load_validation_report_from_artifact(previous_report_uri)

    section_reports_by_name: dict[str, ValidationSectionReport] = {}
    if previous_report is not None:
        section_reports_by_name.update(
            {section.section_name: section for section in previous_report.sections}
        )

    sections_to_rescore = set(SECTION_ORDER)
    if request.config.changed_sections_only:
        sections_to_rescore = set(requested_changed_sections)
        missing_sections = {
            section_name for section_name in SECTION_ORDER if section_name not in section_reports_by_name
        }
        sections_to_rescore.update(missing_sections)

    for section_name in SECTION_ORDER:
        if section_name not in sections_to_rescore:
            continue
        section_reports_by_name[section_name] = _build_section_report(
            section_name=section_name,
            section_text=section_texts.get(section_name, "").strip(),
            source_sentences=source_sentences,
            source_index=source_index,
            request=request,
            validation_config=resolved_validation_config,
            originality_config=resolved_originality_config,
            reference_lines=reference_lines,
        )

    section_reports = [
        section_reports_by_name[section_name]
        for section_name in SECTION_ORDER
        if section_name in section_reports_by_name
    ]
    section_flags = _build_section_flags_from_reports(
        section_reports=section_reports,
        config=resolved_validation_config,
    )

    document_ai_scores = [
        section.ai_score for section in section_reports if section.ai_score is not None
    ]
    document_flagged_spans: list[tuple[int, int]] = []
    document_length = sum(len(text.strip()) for text in section_texts.values() if text.strip()) or 1
    offset_cursor = 0
    for section_name in SECTION_ORDER:
        section_text = section_texts.get(section_name, "").strip()
        section_report = section_reports_by_name.get(section_name)
        if section_report is not None:
            document_flagged_spans.extend(
                [
                    (start + offset_cursor, end + offset_cursor)
                    for start, end in _suspicious_spans_for_section(section_report)
                ]
            )
        offset_cursor += max(1, len(section_text)) + 1

    ai_score = round(mean(document_ai_scores), 4) if document_ai_scores else None
    plagiarism_score = round((_merge_span_lengths(document_flagged_spans) / document_length) * 100, 2)
    routing_decision = _routing_decision_for_report(
        ai_score=ai_score,
        plagiarism_score=plagiarism_score,
        section_flags=section_flags,
        config=resolved_validation_config,
    )

    report = ValidationReport(
        ai_score=ai_score,
        plagiarism_score=plagiarism_score,
        confidence_band=_confidence_band(routing_decision),
        routing_decision=routing_decision,
        deep_validation_used=False,
        sections=section_reports,
        decision_summary=_decision_summary(routing_decision),
    )
    sidecar_payload = {
        "job_id": request.job_id,
        "project_id": request.project_id,
        "mode": request.config.mode,
        "provider_name": resolved_validation_config.provider_name,
        "report": report,
        "section_flags": section_flags,
        "section_status_counts": summarize_status_counts(section.status for section in section_reports),
        "changed_section_ids": request.config.changed_section_ids,
    }
    report_revision = _draft_revision_from_uri(request.current_draft_uri)
    sidecar = store_validation_report_artifact(
        request.project_id,
        request.job_id,
        sidecar_payload,
        mode=request.config.mode,
        revision=report_revision,
    )
    return ValidationServiceResponse(
        job_id=request.job_id,
        output={
            "mode": request.config.mode,
            "ai_score": ai_score,
            "plagiarism_score": plagiarism_score,
            "confidence_band": report.confidence_band,
            "routing_decision": report.routing_decision,
            "section_flags": section_flags,
            "validation_report_uri": sidecar.uri,
            "report": report,
        },
    )
