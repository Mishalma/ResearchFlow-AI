from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Iterable

from app.services.paper_service import build_editor_display_text, build_latex_ready_text
from models.generation import GeneratedPaper, IEEESectionMap, ResearchPaperSchema

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

SECTION_LABELS = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "related_work": "Related Work",
    "methodology": "Methodology",
    "results": "Results",
    "discussion": "Discussion",
    "limitations": "Limitations",
    "conclusion": "Conclusion",
}

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+-]*")
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
CITATION_PATTERN = re.compile(r"\[[0-9,\-\s]+\]|\\cite[t|p]?\{[^}]+\}")
LATEX_PATTERN = re.compile(r"\\[A-Za-z]+(?:\{[^}]*\})*|\$[^$]+\$|\\\([^)]+\\\)|\\\[[^\]]+\\\]")
QUOTED_PATTERN = re.compile(r"\"[^\"]+\"|'[^']+'")
TECHNICAL_ENTITY_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+|[A-Z]{2,}[A-Za-z0-9-]*)\b")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "across",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "those",
    "to",
    "was",
    "were",
    "with",
}
CANONICAL_TOKEN_MAP = {
    "accuracy": "performance",
    "accurate": "performance",
    "achieve": "perform",
    "achieves": "perform",
    "achieved": "perform",
    "approach": "method",
    "architecture": "method",
    "baseline": "benchmark",
    "benchmarks": "benchmark",
    "dataset": "evaluation",
    "datasets": "evaluation",
    "evaluated": "evaluation",
    "evaluations": "evaluation",
    "framework": "method",
    "high": "strong",
    "method": "method",
    "methods": "method",
    "model": "method",
    "models": "method",
    "performed": "perform",
    "performs": "perform",
    "performing": "perform",
    "performance": "perform",
    "pipeline": "method",
    "proposed": "method",
    "results": "perform",
    "robust": "strong",
    "robustly": "strong",
    "standard": "benchmark",
    "standards": "benchmark",
    "strongly": "strong",
    "strong": "strong",
    "system": "method",
    "systems": "method",
    "technique": "method",
    "workflow": "method",
}
PROTECTED_PATTERNS = (
    ("citation", CITATION_PATTERN),
    ("latex", LATEX_PATTERN),
    ("number", NUMBER_PATTERN),
    ("quoted", QUOTED_PATTERN),
    ("entity", TECHNICAL_ENTITY_PATTERN),
)


@dataclass(frozen=True)
class ProtectedSpan:
    placeholder: str
    text: str
    kind: str


@dataclass(frozen=True)
class SafetyCheckResult:
    passed: bool
    reasons: list[str]
    similarity: float


def split_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", normalized):
        cleaned = "\n".join(line.rstrip() for line in block.splitlines()).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def join_paragraphs(paragraphs: Iterable[str]) -> str:
    return "\n\n".join(paragraph.strip() for paragraph in paragraphs if paragraph.strip()).strip()


def split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.replace("\n", " ").split()).strip()
    if not normalized:
        return []
    return [segment.strip() for segment in SENTENCE_PATTERN.split(normalized) if segment.strip()]


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def canonicalize_token(token: str) -> str:
    normalized = token.lower().strip()
    direct_mapping = CANONICAL_TOKEN_MAP.get(normalized)
    if direct_mapping is not None:
        return direct_mapping
    if len(normalized) > 4:
        for suffix in ("ingly", "edly", "ing", "ed", "ly", "es", "s"):
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 2:
                normalized = normalized[: -len(suffix)]
                break
    return CANONICAL_TOKEN_MAP.get(normalized, normalized)


def content_token_set(text: str) -> set[str]:
    tokens = {
        canonicalize_token(token)
        for token in tokenize(text)
        if token not in STOPWORDS and len(token) > 2
    }
    return {token for token in tokens if token and token not in STOPWORDS}


def extract_protected_spans(text: str) -> tuple[str, list[ProtectedSpan]]:
    protected = text
    spans: list[ProtectedSpan] = []
    counter = 0

    for kind, pattern in PROTECTED_PATTERNS:
        for match in list(pattern.finditer(protected)):
            value = match.group(0)
            if not value.strip():
                continue
            placeholder = f"__PAPEREASY_PROTECTED_{counter:04d}__"
            counter += 1
            protected = protected.replace(value, placeholder, 1)
            spans.append(ProtectedSpan(placeholder=placeholder, text=value, kind=kind))

    return protected, spans


def restore_protected_spans(text: str, spans: Iterable[ProtectedSpan]) -> str:
    restored = text
    for span in spans:
        restored = restored.replace(span.placeholder, span.text)
    return restored


def protected_signature(text: str) -> dict[str, list[str]]:
    signature: dict[str, list[str]] = {}
    for kind, pattern in PROTECTED_PATTERNS:
        signature[kind] = [match.group(0) for match in pattern.finditer(text)]
    return signature


def semantic_similarity(source: str, candidate: str) -> float:
    source_tokens = content_token_set(source)
    candidate_tokens = content_token_set(candidate)
    if not source_tokens and not candidate_tokens:
        return 1.0
    if not source_tokens or not candidate_tokens:
        return 0.0
    jaccard = len(source_tokens & candidate_tokens) / len(source_tokens | candidate_tokens)
    sequence = difflib.SequenceMatcher(a=source.lower(), b=candidate.lower()).ratio()
    return round((jaccard * 0.75) + (sequence * 0.25), 4)


def verify_rewrite_safety(
    *,
    original: str,
    rewritten: str,
    similarity_threshold: float,
) -> SafetyCheckResult:
    reasons: list[str] = []
    original_signature = protected_signature(original)
    rewritten_signature = protected_signature(rewritten)

    for kind in ("citation", "latex", "number"):
        if original_signature[kind] != rewritten_signature[kind]:
            reasons.append(f"{kind}_tokens_changed")

    similarity = semantic_similarity(original, rewritten)
    if similarity < similarity_threshold:
        reasons.append("semantic_similarity_too_low")

    return SafetyCheckResult(
        passed=not reasons,
        reasons=reasons,
        similarity=similarity,
    )


def build_diff_summary(original: str, rewritten: str, *, limit: int = 4) -> list[str]:
    if original.strip() == rewritten.strip():
        return ["No stylistic rewrite was applied."]

    summary: list[str] = []
    matcher = difflib.SequenceMatcher(a=original.split(), b=rewritten.split())
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_chunk = " ".join(original.split()[i1:i2]).strip()
        new_chunk = " ".join(rewritten.split()[j1:j2]).strip()
        if tag == "replace" and old_chunk and new_chunk:
            summary.append(f"Rephrased '{old_chunk[:60]}' to '{new_chunk[:60]}'.")
        elif tag == "delete" and old_chunk:
            summary.append(f"Removed repetitive phrase '{old_chunk[:60]}'.")
        elif tag == "insert" and new_chunk:
            summary.append(f"Introduced more varied phrasing '{new_chunk[:60]}'.")
        if len(summary) >= limit:
            break
    return summary or ["Applied targeted stylistic variation while preserving protected content."]


def build_section_text_map(paper: ResearchPaperSchema) -> dict[str, str]:
    return {
        "abstract": paper.abstract,
        "introduction": paper.sections.introduction,
        "related_work": paper.sections.related_work,
        "methodology": paper.sections.methodology,
        "results": paper.sections.results,
        "discussion": paper.sections.discussion,
        "limitations": paper.sections.limitations,
        "conclusion": paper.sections.conclusion,
    }


def build_generated_paper(
    *,
    source_paper: ResearchPaperSchema,
    section_texts: dict[str, str],
) -> GeneratedPaper:
    updated_paper = ResearchPaperSchema(
        title=source_paper.title,
        abstract=section_texts.get("abstract", "").strip() or source_paper.abstract,
        keywords=list(source_paper.keywords),
        sections=IEEESectionMap(
            introduction=section_texts.get("introduction", "").strip() or source_paper.sections.introduction,
            related_work=section_texts.get("related_work", "").strip() or source_paper.sections.related_work,
            methodology=section_texts.get("methodology", "").strip() or source_paper.sections.methodology,
            results=section_texts.get("results", "").strip() or source_paper.sections.results,
            discussion=section_texts.get("discussion", "").strip() or source_paper.sections.discussion,
            limitations=section_texts.get("limitations", "").strip() or source_paper.sections.limitations,
            conclusion=section_texts.get("conclusion", "").strip() or source_paper.sections.conclusion,
        ),
        references=list(source_paper.references),
    )
    return GeneratedPaper(
        paper=updated_paper,
        formatted_text=build_editor_display_text(updated_paper),
        latex_ready=build_latex_ready_text(updated_paper),
    )


def coerce_optional_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    return {}
