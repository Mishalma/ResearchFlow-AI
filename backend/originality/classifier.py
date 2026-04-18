from __future__ import annotations

from originality.config import OriginalityConfig
from originality.remediation import build_remediation_actions
from originality.schemas import OriginalitySpan, ProviderFinding
from originality.utils import (
    bibliography_has_source,
    build_reference_lookup,
    extract_nearby_citations,
    looks_like_self_overlap,
    normalize_whitespace,
    span_inside_quote,
)

COMMON_PHRASE_PATTERNS = (
    "state of the art",
    "related work",
    "experimental setup",
    "results and discussion",
    "in conclusion",
)

BOILERPLATE_PATTERNS = (
    "all rights reserved",
    "this work was supported by",
    "conflicts of interest",
    "ethics statement",
)


def classify_section_findings(
    *,
    section_name: str,
    section_text: str,
    findings: list[ProviderFinding],
    reference_lines: list[str],
    author_metadata: object,
    config: OriginalityConfig,
) -> list[OriginalitySpan]:
    bibliography_lookup = build_reference_lookup(reference_lines)
    spans: list[OriginalitySpan] = []
    for finding in findings:
        nearby_citations = extract_nearby_citations(
            section_text,
            start_char=finding.start_char,
            end_char=finding.end_char,
            window=config.quoted_citation_window_chars,
        )
        quoted = span_inside_quote(
            section_text,
            start_char=finding.start_char,
            end_char=finding.end_char,
        )
        in_bibliography = bibliography_has_source(
            title=finding.matched_source_title,
            url=finding.matched_source_url,
            bibliography_lookup=bibliography_lookup,
        )
        self_overlap = looks_like_self_overlap(
            matched_source_title=finding.matched_source_title,
            matched_source_url=finding.matched_source_url,
            author_metadata=author_metadata,
        )
        classification = _classify(
            section_name=section_name,
            finding=finding,
            cited_nearby=bool(nearby_citations),
            quoted=quoted,
            in_bibliography=in_bibliography,
            self_overlap=self_overlap,
            config=config,
        )
        spans.append(
            OriginalitySpan(
                section_name=section_name,
                start_char=finding.start_char,
                end_char=finding.end_char,
                matched_text=finding.matched_text,
                provider_name=str(finding.metadata.get("provider_name") or finding.metadata.get("provider") or "provider").strip(),
                similarity_score=finding.similarity_score,
                matched_source_title=finding.matched_source_title,
                matched_source_url=finding.matched_source_url,
                classification=classification,
                severity=_adjust_severity(
                    base_severity=finding.severity,
                    classification=classification,
                    cited_nearby=bool(nearby_citations),
                    quoted=quoted,
                ),
                remediation_actions=build_remediation_actions(
                    classification=classification,
                    cited_nearby=bool(nearby_citations),
                    quoted=quoted,
                ),
                metadata={
                    **finding.metadata,
                    "nearby_citations": nearby_citations,
                    "quoted": quoted,
                    "source_in_bibliography": in_bibliography,
                    "possible_self_overlap": self_overlap,
                },
            )
        )
    return spans


def _classify(
    *,
    section_name: str,
    finding: ProviderFinding,
    cited_nearby: bool,
    quoted: bool,
    in_bibliography: bool,
    self_overlap: bool,
    config: OriginalityConfig,
) -> str:
    lowered_text = normalize_whitespace(finding.matched_text).lower()
    if quoted and cited_nearby:
        return "quoted_and_cited"
    if len(lowered_text) <= config.common_phrase_max_chars and (
        any(pattern in lowered_text for pattern in COMMON_PHRASE_PATTERNS)
        or len(lowered_text.split()) <= 6
    ):
        return "common_phrase"
    if any(pattern in lowered_text for pattern in BOILERPLATE_PATTERNS):
        return "boilerplate"
    if self_overlap:
        return "possible_self_overlap"
    if cited_nearby or in_bibliography:
        if finding.severity >= config.blocking_severity_threshold:
            return "manual_review_required"
        return "uncited_close_paraphrase"
    if finding.severity >= config.blocking_severity_threshold or len(lowered_text) >= 140:
        return "likely_unattributed_copying"
    if finding.severity >= config.manual_review_severity_threshold:
        return "uncited_close_paraphrase"
    if section_name in {"methodology", "results"} and finding.severity >= 0.35:
        return "manual_review_required"
    return "manual_review_required"


def _adjust_severity(
    *,
    base_severity: float,
    classification: str,
    cited_nearby: bool,
    quoted: bool,
) -> float:
    severity = float(base_severity)
    if classification in {"quoted_and_cited", "common_phrase", "boilerplate"}:
        severity *= 0.25
    elif classification == "possible_self_overlap":
        severity = max(severity, 0.45)
    elif classification == "uncited_close_paraphrase":
        severity = max(severity, 0.55)
    elif classification == "likely_unattributed_copying":
        severity = max(severity, 0.85)
    elif classification == "manual_review_required":
        severity = max(severity, 0.5)
    if cited_nearby and not quoted and classification != "quoted_and_cited":
        severity = max(0.0, severity - 0.08)
    return round(min(1.0, max(0.0, severity)), 4)
