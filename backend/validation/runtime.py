from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import mean

from core.config import Settings, get_settings
from jobs.artifacts import (
    load_extracted_text_artifact,
    load_generated_draft_artifact,
    load_validation_report_from_artifact,
    store_validation_report_artifact,
)
from models.validation import (
    ValidationCandidateScore,
    ValidationCandidateScoringRequest,
    ValidationCandidateScoringResponse,
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
from validation.desklib_detector import get_desklib_detector
from validation.stylometry import iter_sentence_spans, tokenize_words

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
    if routing_decision == "accepted":
        return "low"
    return "unknown"


def _decision_summary(routing_decision: str, *, mode: str, failure_reasons: list[str] | None = None) -> str:
    reasons = failure_reasons or []
    if mode == "ai_check":
        if routing_decision == "accepted":
            return "The manuscript stayed within the 10% AI acceptance threshold and can proceed to overlap review."
        return "The manuscript stayed above the 10% AI acceptance threshold and needs humanizer remediation."
    if routing_decision == "accepted":
        return "The manuscript stayed within the 10% acceptance thresholds for AI and source overlap."
    if "ai_threshold_exceeded" in reasons and "overlap_threshold_exceeded" in reasons:
        return "The manuscript stayed above the AI and source-overlap acceptance thresholds."
    if "ai_threshold_exceeded" in reasons:
        return "The manuscript stayed above the 10% AI acceptance threshold."
    if "overlap_threshold_exceeded" in reasons:
        return "The manuscript stayed above the 10% source-overlap acceptance threshold."
    return "Validation is pending."


def _draft_revision_from_uri(uri: str) -> str:
    match = re.search(r"draft_v(\d+)\.json$", str(uri or ""))
    if not match:
        return "v1"
    return f"v{match.group(1)}"


def _section_status(
    spans: list,
    *,
    ai_score: float | None,
    plagiarism_score: float,
    config: ValidationConfig,
) -> tuple[str, str, list[str]]:
    classifications = {span.classification for span in spans}
    severe = (
        "likely_unattributed_copying" in classifications
        or (ai_score is not None and ai_score > config.ai_severe_threshold)
        or plagiarism_score > config.plagiarism_severe_threshold
    )
    flagged = (
        severe
        or bool(classifications & {"possible_self_overlap", "manual_review_required", "uncited_close_paraphrase"})
        or (ai_score is not None and ai_score > config.ai_accept_threshold)
        or plagiarism_score > config.plagiarism_accept_threshold
    )

    if severe:
        return (
            "flagged",
            "severe",
            ["This section stayed above the acceptance threshold with severe AI or source-overlap signals."],
        )
    if flagged:
        return (
            "flagged",
            "medium",
            ["This section stayed above the 10% acceptance threshold and was flagged for remediation."],
        )
    if spans:
        return (
            "accepted_with_notes",
            "low",
            ["Only citation-safe or low-risk overlap was detected in this section."],
        )
    return ("accepted", "low", ["This section stayed within the 10% acceptance thresholds."])


def _section_ai_status(*, ai_score: float | None, config: ValidationConfig) -> tuple[str, str, list[str]]:
    if ai_score is None:
        return ("accepted", "low", ["This section did not produce an AI score."])
    if ai_score > config.ai_severe_threshold:
        return (
            "flagged",
            "severe",
            ["This section stayed above the severe AI threshold and needs remediation."],
        )
    if ai_score > config.ai_accept_threshold:
        return (
            "flagged",
            "medium",
            ["This section stayed above the 10% AI acceptance threshold and was flagged for remediation."],
        )
    return ("accepted", "low", ["This section stayed within the 10% AI acceptance threshold."])


def _routing_decision_for_report(
    *,
    ai_score: float | None,
    plagiarism_score: float,
    section_flags: list[ValidationSectionFlag],
    config: ValidationConfig,
) -> str:
    has_any_flag = any(flag.risk in {"medium", "severe"} for flag in section_flags)
    if (
        (ai_score is not None and ai_score > config.ai_accept_threshold)
        or plagiarism_score > config.plagiarism_accept_threshold
        or has_any_flag
    ):
        return "flagged"
    return "accepted"


def _routing_decision_for_ai_check(
    *,
    ai_score: float | None,
    section_flags: list[ValidationSectionFlag],
    config: ValidationConfig,
) -> str:
    has_any_flag = any(flag.risk in {"medium", "severe"} for flag in section_flags)
    if (ai_score is not None and ai_score > config.ai_accept_threshold) or has_any_flag:
        return "flagged"
    return "accepted"


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
        if section.ai_score is not None and section.ai_score > config.ai_accept_threshold:
            section_flags.append(
                ValidationSectionFlag(
                    section_id=section.section_name,
                    flag_type="ai",
                    score=round(section.ai_score, 4),
                    risk="severe" if section.ai_score > config.ai_severe_threshold else "medium",
                    summary=f"{section.section_name.replace('_', ' ').title()} stayed above the AI acceptance threshold.",
                )
            )
        suspicious_spans = _suspicious_spans_for_section(section)
        if suspicious_spans and section.plagiarism_score > config.plagiarism_accept_threshold:
            section_flags.append(
                ValidationSectionFlag(
                    section_id=section.section_name,
                    flag_type="plagiarism",
                    score=section.plagiarism_score,
                    risk="severe"
                    if section.plagiarism_score > config.plagiarism_severe_threshold
                    else "medium",
                    summary=f"{section.section_name.replace('_', ' ').title()} stayed above the overlap acceptance threshold.",
                )
            )
    return section_flags


def _ai_score_for_section(
    text: str,
    *,
    config: ValidationConfig,
) -> tuple[float | None, dict[str, float | int | str]]:
    if not text.strip():
        return None, {}
    detector = get_desklib_detector(
        config,
        project_id=get_settings().google_cloud_project,
    )
    prediction = detector.score_text(text)
    return prediction.score, prediction.as_metadata()


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
        if "desklib_probability" in ai_metadata:
            metadata_summary.append(
                "AI detector "
                f"{ai_metadata.get('desklib_probability', 0.0):.2f} "
                f"({ai_metadata.get('ai_detector_model_id', 'desklib')})"
            )
        else:
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


def _overlap_score_for_text(
    *,
    section_name: str,
    section_text: str,
    source_sentences: list[_SourceSentence],
    source_index: dict[tuple[str, ...], set[int]],
    project_id: str,
    validation_config: ValidationConfig,
    originality_config: OriginalityConfig,
    reference_lines: list[str] | None = None,
) -> float:
    scan = _detect_section_overlap(
        section_name=section_name,
        section_text=section_text,
        source_sentences=source_sentences,
        source_index=source_index,
        project_id=project_id,
        config=validation_config,
    )
    classified_spans = classify_section_findings(
        section_name=section_name,
        section_text=section_text,
        findings=scan.spans,
        reference_lines=reference_lines or [],
        author_metadata=None,
        config=originality_config,
    )
    suspicious_spans = [
        (span.start_char, span.end_char)
        for span in classified_spans
        if span.classification not in {"quoted_and_cited", "common_phrase", "boilerplate"}
    ]
    section_length = max(1, len(section_text.strip()))
    return round((_merge_span_lengths(suspicious_spans) / section_length) * 100, 2)


def _build_ai_only_section_report(
    *,
    section_name: str,
    section_text: str,
    validation_config: ValidationConfig,
) -> ValidationSectionReport:
    section_ai_score, ai_metadata = _ai_score_for_section(
        section_text,
        config=validation_config,
    )
    status, risk, summary = _section_ai_status(
        ai_score=section_ai_score,
        config=validation_config,
    )
    if ai_metadata.get("desklib_probability") is not None:
        summary = summary + [
            "AI detector "
            f"{ai_metadata.get('desklib_probability', 0.0):.2f} "
            f"({ai_metadata.get('ai_detector_model_id', 'desklib')})"
        ]
    return ValidationSectionReport(
        section_name=section_name,
        ai_score=section_ai_score,
        plagiarism_score=0.0,
        status=status,
        risk=risk,
        summary=summary,
        spans=[],
    )


def _candidate_min_ai_drop(
    *,
    original_ai_score: float | None,
    request_config,
    validation_config: ValidationConfig,
) -> float:
    if original_ai_score is None:
        return 0.0
    if original_ai_score > 0.90:
        return float(request_config.min_ai_drop_high)
    if original_ai_score > validation_config.ai_severe_threshold:
        return float(request_config.min_ai_drop_medium)
    return 0.0005


async def score_validation_candidates(
    request: ValidationCandidateScoringRequest,
    *,
    settings: Settings | None = None,
    validation_config: ValidationConfig | None = None,
    originality_config: OriginalityConfig | None = None,
) -> ValidationCandidateScoringResponse:
    resolved_settings = settings or get_settings()
    resolved_validation_config = validation_config or ValidationConfig.from_settings(resolved_settings)
    resolved_originality_config = originality_config or OriginalityConfig.from_settings(resolved_settings)
    source_text = (request.source_text or "").strip()
    if not source_text and request.extracted_text_uri:
        source_text = load_extracted_text_artifact(request.extracted_text_uri)

    source_sentences: list[_SourceSentence] = []
    source_index: dict[tuple[str, ...], set[int]] = {}
    compute_overlap = bool(request.config.compute_overlap)
    ai_only = request.config.accept_mode == "ai_only"
    if compute_overlap:
        source_sentences, source_index = _build_source_index(
            source_text,
            ngram_size=resolved_validation_config.overlap_ngram_size,
            min_tokens=resolved_validation_config.overlap_sentence_min_tokens,
        )
    results: list[ValidationCandidateScore] = []

    for candidate in request.candidates:
        ai_score, _metadata = _ai_score_for_section(
            candidate.text,
            config=resolved_validation_config,
        )
        overlap_score = 0.0
        if compute_overlap:
            overlap_score = _overlap_score_for_text(
                section_name=candidate.section_id,
                section_text=candidate.text,
                source_sentences=source_sentences,
                source_index=source_index,
                project_id=request.project_id,
                validation_config=resolved_validation_config,
                originality_config=resolved_originality_config,
            )

        original_ai_score = candidate.original_ai_score
        original_overlap_score = candidate.original_overlap_score
        if candidate.original_text:
            if original_ai_score is None:
                original_ai_score, _ = _ai_score_for_section(
                    candidate.original_text,
                    config=resolved_validation_config,
                )
            if compute_overlap and original_overlap_score is None:
                original_overlap_score = _overlap_score_for_text(
                    section_name=candidate.section_id,
                    section_text=candidate.original_text,
                    source_sentences=source_sentences,
                    source_index=source_index,
                    project_id=request.project_id,
                    validation_config=resolved_validation_config,
                    originality_config=resolved_originality_config,
                )

        score_delta = (
            round(float(original_ai_score) - float(ai_score), 4)
            if original_ai_score is not None and ai_score is not None
            else None
        )
        overlap_delta = (
            round(float(overlap_score) - float(original_overlap_score), 2)
            if compute_overlap and original_overlap_score is not None
            else None
        )

        rejection_reasons: list[str] = []
        min_drop = _candidate_min_ai_drop(
            original_ai_score=original_ai_score,
            request_config=request.config,
            validation_config=resolved_validation_config,
        )
        ai_accepted = bool(
            ai_score is not None
            and (
                ai_score <= request.config.ai_accept_threshold
                or (score_delta is not None and score_delta >= min_drop)
            )
        )
        if not ai_accepted:
            rejection_reasons.append("ai_not_improved")

        overlap_accepted = True
        if compute_overlap and not ai_only:
            overlap_improved = bool(
                original_overlap_score is not None
                and overlap_score < float(original_overlap_score)
            )
            overlap_accepted = (
                overlap_score <= request.config.overlap_accept_threshold
                or overlap_improved
            )
            if overlap_delta is not None and overlap_delta > request.config.max_overlap_increase:
                overlap_accepted = False
                rejection_reasons.append("overlap_increased")
            if not overlap_accepted and "overlap_increased" not in rejection_reasons:
                rejection_reasons.append("overlap_above_threshold")

        results.append(
            ValidationCandidateScore(
                candidate_id=candidate.candidate_id,
                section_id=candidate.section_id,
                ai_score=ai_score,
                overlap_score=overlap_score,
                score_delta=score_delta,
                overlap_delta=overlap_delta,
                accepted=ai_accepted and overlap_accepted,
                rejection_reasons=rejection_reasons,
            )
        )

    return ValidationCandidateScoringResponse(job_id=request.job_id, results=results)


def _document_ai_score(section_reports: list[ValidationSectionReport]) -> float | None:
    document_ai_scores = [section.ai_score for section in section_reports if section.ai_score is not None]
    return round(mean(document_ai_scores), 4) if document_ai_scores else None


def _initial_scores_from_previous(previous_report: ValidationReport | None) -> tuple[float | None, float | None]:
    if previous_report is None:
        return None, None
    initial_ai_score = (
        previous_report.initial_ai_score
        if previous_report.initial_ai_score is not None
        else previous_report.ai_score
    )
    initial_plagiarism_score = (
        previous_report.initial_plagiarism_score
        if previous_report.initial_plagiarism_score is not None
        else previous_report.plagiarism_score
    )
    return initial_ai_score, initial_plagiarism_score


def _validation_sidecar_payload(
    *,
    request: ValidationServiceRequest,
    config: ValidationConfig,
    report: ValidationReport,
    section_flags: list[ValidationSectionFlag],
) -> dict[str, object]:
    return {
        "job_id": request.job_id,
        "project_id": request.project_id,
        "mode": request.config.mode,
        "provider_name": config.provider_name,
        "ai_detector": {
            "backend": config.ai_detector_backend,
            "model_id": config.ai_detector_model_id,
            "max_length": config.ai_detector_max_length,
            "batch_size": config.ai_detector_batch_size,
        },
        "report": report,
        "section_flags": section_flags,
        "section_status_counts": summarize_status_counts(section.status for section in report.sections),
        "changed_section_ids": request.config.changed_section_ids,
        "failure_reasons": report.failure_reasons,
    }


async def _execute_ai_check(
    request: ValidationServiceRequest,
    *,
    settings: Settings,
    validation_config: ValidationConfig,
) -> ValidationServiceResponse:
    draft = load_generated_draft_artifact(request.current_draft_uri)
    section_texts = build_section_map(humanized_draft=None, paper_snapshot=draft)

    requested_changed_sections = set(request.config.changed_section_ids)
    if request.config.changed_sections_only and not requested_changed_sections:
        raise ValueError("changed_section_ids is required when changed_sections_only=true.")

    previous_report = None
    previous_report_uri = request.artifacts.previous_validation_report_uri
    if request.config.changed_sections_only:
        if not previous_report_uri:
            raise ValueError("previous_validation_report_uri is required when changed_sections_only=true.")
        previous_report = load_validation_report_from_artifact(previous_report_uri)

    section_reports_by_name: dict[str, ValidationSectionReport] = {}
    if previous_report is not None:
        section_reports_by_name.update({section.section_name: section for section in previous_report.sections})

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
        section_reports_by_name[section_name] = _build_ai_only_section_report(
            section_name=section_name,
            section_text=section_texts.get(section_name, "").strip(),
            validation_config=validation_config,
        )

    section_reports = [
        section_reports_by_name[section_name]
        for section_name in SECTION_ORDER
        if section_name in section_reports_by_name
    ]
    section_flags = [
        ValidationSectionFlag(
            section_id=section.section_name,
            flag_type="ai",
            score=round(section.ai_score or 0.0, 4),
            risk=section.risk,
            summary=f"{section.section_name.replace('_', ' ').title()} stayed above the AI acceptance threshold.",
        )
        for section in section_reports
        if section.ai_score is not None and section.ai_score > validation_config.ai_accept_threshold
    ]
    ai_score = _document_ai_score(section_reports)
    routing_decision = _routing_decision_for_ai_check(
        ai_score=ai_score,
        section_flags=section_flags,
        config=validation_config,
    )
    initial_ai_score, initial_plagiarism_score = _initial_scores_from_previous(previous_report)
    if initial_ai_score is None:
        initial_ai_score = ai_score

    failure_reasons = ["ai_threshold_exceeded"] if routing_decision == "flagged" else []
    report = ValidationReport(
        ai_score=ai_score,
        plagiarism_score=0.0,
        confidence_band=_confidence_band(routing_decision),
        routing_decision=routing_decision,
        sections=section_reports,
        decision_summary=_decision_summary(routing_decision, mode="ai_check", failure_reasons=failure_reasons),
        initial_ai_score=initial_ai_score,
        initial_plagiarism_score=initial_plagiarism_score,
        final_ai_score=ai_score,
        final_plagiarism_score=None,
        failure_reasons=failure_reasons,
    )
    sidecar = store_validation_report_artifact(
        request.project_id,
        request.job_id,
        _validation_sidecar_payload(
            request=request,
            config=validation_config,
            report=report,
            section_flags=section_flags,
        ),
        mode=request.config.mode,
        revision=_draft_revision_from_uri(request.current_draft_uri),
    )
    return ValidationServiceResponse(
        job_id=request.job_id,
        output={
            "mode": request.config.mode,
            "ai_score": ai_score,
            "plagiarism_score": 0.0,
            "confidence_band": report.confidence_band,
            "routing_decision": report.routing_decision,
            "section_flags": section_flags,
            "validation_report_uri": sidecar.uri,
            "report": report,
            "failure_reasons": failure_reasons,
        },
    )


async def _execute_final_report(
    request: ValidationServiceRequest,
    *,
    settings: Settings,
    validation_config: ValidationConfig,
    originality_config: OriginalityConfig,
) -> ValidationServiceResponse:
    draft = load_generated_draft_artifact(request.current_draft_uri)
    extracted_text_uri = request.artifacts.extracted_text_uri
    if not extracted_text_uri:
        raise ValueError("Validation requests require artifacts.extracted_text_uri.")
    source_text = load_extracted_text_artifact(extracted_text_uri)
    previous_report = None
    if request.artifacts.previous_validation_report_uri:
        previous_report = load_validation_report_from_artifact(request.artifacts.previous_validation_report_uri)

    section_texts = build_section_map(humanized_draft=None, paper_snapshot=draft)
    source_sentences, source_index = _build_source_index(
        source_text,
        ngram_size=validation_config.overlap_ngram_size,
        min_tokens=validation_config.overlap_sentence_min_tokens,
    )
    reference_lines = list(draft.paper.references)
    section_reports = [
        _build_section_report(
            section_name=section_name,
            section_text=section_texts.get(section_name, "").strip(),
            source_sentences=source_sentences,
            source_index=source_index,
            request=request,
            validation_config=validation_config,
            originality_config=originality_config,
            reference_lines=reference_lines,
        )
        for section_name in SECTION_ORDER
    ]
    section_flags = _build_section_flags_from_reports(
        section_reports=section_reports,
        config=validation_config,
    )

    ai_score = _document_ai_score(section_reports)
    document_flagged_spans: list[tuple[int, int]] = []
    document_length = sum(len(text.strip()) for text in section_texts.values() if text.strip()) or 1
    offset_cursor = 0
    for section_name in SECTION_ORDER:
        section_text = section_texts.get(section_name, "").strip()
        section_report = next((section for section in section_reports if section.section_name == section_name), None)
        if section_report is not None:
            document_flagged_spans.extend(
                [(start + offset_cursor, end + offset_cursor) for start, end in _suspicious_spans_for_section(section_report)]
            )
        offset_cursor += max(1, len(section_text)) + 1

    plagiarism_score = round((_merge_span_lengths(document_flagged_spans) / document_length) * 100, 2)
    routing_decision = _routing_decision_for_report(
        ai_score=ai_score,
        plagiarism_score=plagiarism_score,
        section_flags=section_flags,
        config=validation_config,
    )
    initial_ai_score, initial_plagiarism_score = _initial_scores_from_previous(previous_report)
    if initial_ai_score is None:
        initial_ai_score = ai_score
    if initial_plagiarism_score is None:
        initial_plagiarism_score = plagiarism_score

    failure_reasons: list[str] = []
    if ai_score is not None and ai_score > validation_config.ai_accept_threshold:
        failure_reasons.append("ai_threshold_exceeded")
    if plagiarism_score > validation_config.plagiarism_accept_threshold:
        failure_reasons.append("overlap_threshold_exceeded")

    report = ValidationReport(
        ai_score=ai_score,
        plagiarism_score=plagiarism_score,
        confidence_band=_confidence_band(routing_decision),
        routing_decision=routing_decision,
        sections=section_reports,
        decision_summary=_decision_summary(routing_decision, mode="final_report", failure_reasons=failure_reasons),
        initial_ai_score=initial_ai_score,
        initial_plagiarism_score=initial_plagiarism_score,
        final_ai_score=ai_score,
        final_plagiarism_score=plagiarism_score,
        failure_reasons=failure_reasons,
    )
    sidecar = store_validation_report_artifact(
        request.project_id,
        request.job_id,
        _validation_sidecar_payload(
            request=request,
            config=validation_config,
            report=report,
            section_flags=section_flags,
        ),
        mode=request.config.mode,
        revision=_draft_revision_from_uri(request.current_draft_uri),
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
            "failure_reasons": failure_reasons,
        },
    )


async def execute_validation(
    request: ValidationServiceRequest,
    *,
    settings: Settings | None = None,
    validation_config: ValidationConfig | None = None,
    originality_config: OriginalityConfig | None = None,
) -> ValidationServiceResponse:
    resolved_settings = settings or get_settings()
    resolved_validation_config = validation_config or ValidationConfig.from_settings(resolved_settings)
    resolved_originality_config = originality_config or OriginalityConfig.from_settings(resolved_settings)
    if request.config.mode == "ai_check":
        return await _execute_ai_check(
            request,
            settings=resolved_settings,
            validation_config=resolved_validation_config,
        )
    return await _execute_final_report(
        request,
        settings=resolved_settings,
        validation_config=resolved_validation_config,
        originality_config=resolved_originality_config,
    )


async def execute_fast_validation(
    request: ValidationServiceRequest,
    *,
    settings: Settings | None = None,
    validation_config: ValidationConfig | None = None,
    originality_config: OriginalityConfig | None = None,
) -> ValidationServiceResponse:
    return await execute_validation(
        request,
        settings=settings,
        validation_config=validation_config,
        originality_config=originality_config,
    )
