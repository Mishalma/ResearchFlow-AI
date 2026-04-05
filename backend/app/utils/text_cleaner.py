from __future__ import annotations

import re
import unicodedata

CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
WHITESPACE_RE = re.compile(r"\s+")


def clean_extracted_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    without_control_characters = CONTROL_CHARACTERS_RE.sub(" ", normalized)
    collapsed_whitespace = WHITESPACE_RE.sub(" ", without_control_characters)
    return collapsed_whitespace.strip()
