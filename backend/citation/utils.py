from __future__ import annotations

import json
import math
import re
from collections import Counter
from html import unescape
from typing import Any

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "using",
    "with",
}

BIOMEDICAL_TERMS = {
    "biomedical",
    "bioinformatics",
    "clinical",
    "disease",
    "diagnosis",
    "drug",
    "genome",
    "gene",
    "medical",
    "patient",
    "proteomics",
    "rna",
    "tumor",
    "therapy",
    "pharmacology",
    "epidemiology",
    "microbiology",
    "cell",
}

DATASET_TERMS = {
    "dataset",
    "benchmark",
    "corpus",
    "imagenet",
    "cifar",
    "pubmed",
    "mimic",
    "squad",
}

TOOL_TERMS = {
    "framework",
    "tool",
    "model",
    "pipeline",
    "library",
    "algorithm",
    "transformer",
    "bert",
    "gpt",
    "resnet",
    "pytorch",
    "tensorflow",
}

COMPARATIVE_MARKERS = {
    "compared",
    "outperform",
    "baseline",
    "state-of-the-art",
    "sota",
    "benchmark",
    "prior work",
    "previous studies",
}

OWN_WORK_MARKERS = {
    "this work",
    "this paper",
    "our approach",
    "we propose",
    "we present",
    "we evaluate",
    "our method",
    "our results",
}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def normalize_whitespace(text: str) -> str:
    return " ".join(unescape(str(text or "")).replace("\n", " ").split()).strip()


def normalize_title(title: str) -> str:
    return " ".join(tokenize(title))


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    normalized = re.sub(r"^https?://(dx\.)?doi\.org/", "", normalized, flags=re.IGNORECASE)
    match = DOI_PATTERN.search(normalized)
    return match.group(0).lower() if match else None


def extract_doi(value: str | None) -> str | None:
    if not value:
        return None
    match = DOI_PATTERN.search(value)
    return match.group(0).lower() if match else None


def is_biomedical(text: str, paper_domain: str | None = None) -> bool:
    haystack = f"{text} {paper_domain or ''}".lower()
    return any(term in haystack for term in BIOMEDICAL_TERMS)


def detect_claim_type(section_name: str, claim_text: str) -> str:
    normalized = claim_text.lower()
    tokens = set(tokenize(claim_text))
    if section_name == "related_work":
        return "prior_work_claim"
    if is_biomedical(claim_text):
        return "biomedical_mechanistic_claim"
    if any(marker in normalized for marker in COMPARATIVE_MARKERS):
        return "comparative_state_of_the_art_claim"
    if tokens & DATASET_TERMS or tokens & TOOL_TERMS:
        if section_name == "methodology":
            return "methodology_provenance_claim"
        return "dataset_tool_claim"
    if section_name in {"introduction", "abstract"}:
        return "background_claim"
    if section_name in {"discussion", "conclusion"}:
        return "domain_fact_claim"
    if section_name == "methodology":
        return "methodology_provenance_claim"
    return "domain_fact_claim"


def claim_requires_citation(section_name: str, claim_text: str, claim_type: str) -> bool:
    normalized = claim_text.lower()
    if any(marker in normalized for marker in OWN_WORK_MARKERS):
        if claim_type in {"dataset_tool_claim", "methodology_provenance_claim"}:
            return True
        return False
    if section_name == "limitations":
        return False
    if section_name == "results" and claim_type not in {
        "comparative_state_of_the_art_claim",
        "dataset_tool_claim",
        "methodology_provenance_claim",
    }:
        return False
    return True


def provider_route_for_claim(claim_type: str, claim_text: str, paper_domain: str | None = None) -> list[str]:
    if claim_type == "biomedical_mechanistic_claim" or is_biomedical(claim_text, paper_domain):
        return ["pubmed", "semantic_scholar", "openalex"]
    if claim_type in {"prior_work_claim", "comparative_state_of_the_art_claim"}:
        return ["semantic_scholar", "openalex"]
    if claim_type in {"dataset_tool_claim", "methodology_provenance_claim"}:
        return ["semantic_scholar", "openalex"]
    return ["openalex", "semantic_scholar"]


def build_provider_summary(records: list[str]) -> dict[str, int]:
    counter = Counter(records)
    return {provider: int(count) for provider, count in counter.items()}


def truncate_query(text: str, *, max_tokens: int = 16) -> str:
    normalized = normalize_whitespace(text)
    if not normalized:
        return ""
    tokens = normalized.split()
    return " ".join(tokens[:max_tokens]).strip()


def candidate_dedupe_key(*, title: str, doi: str | None, year: int | None) -> str:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    return f"title:{normalize_title(title)}:{year or 'na'}"


def clamp_score(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(max(0.0, min(1.0, value)), 4)


def merge_dicts(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    return merged


def ensure_json_serializable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): ensure_json_serializable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ensure_json_serializable(item) for item in value]
        return str(value)
