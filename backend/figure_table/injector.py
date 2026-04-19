"""Idempotent manuscript enrichment with figure and table references."""

from __future__ import annotations

import logging
import re

from figure_table.models import RenderedFigure, figure_reference_label

logger = logging.getLogger("papereasy.backend.figure_table.injector")

_SECTION_HEADING_MAP = {
    "abstract": re.compile(r"^Abstract$", re.MULTILINE),
    "introduction": re.compile(r"^I\.\s+INTRODUCTION$", re.MULTILINE),
    "related_work": re.compile(r"^II\.\s+RELATED WORK$", re.MULTILINE),
    "methodology": re.compile(r"^III\.\s+METHODOLOGY$", re.MULTILINE),
    "results": re.compile(r"^IV\.\s+RESULTS$", re.MULTILINE),
    "discussion": re.compile(r"^V\.\s+DISCUSSION$", re.MULTILINE),
    "limitations": re.compile(r"^VI\.\s+LIMITATIONS$", re.MULTILINE),
    "conclusion": re.compile(r"^VII\.\s+CONCLUSION$", re.MULTILINE),
    "references": re.compile(r"^References$", re.MULTILINE),
}


class ManuscriptInjector:
    """Inject figure/table references and placement markers into manuscript text."""

    def inject(self, manuscript_text: str, rendered: list[RenderedFigure]) -> str:
        """Inject in-text references and soft placement markers into manuscript text."""

        enriched = str(manuscript_text or "")
        if not enriched.strip():
            return enriched

        for entry in rendered:
            if not entry.render_success:
                continue

            marker = f"%% FIGURE_PLACEMENT: {entry.spec.id}"
            reference = figure_reference_label(entry.spec)
            if marker in enriched:
                continue

            placement_hint = entry.spec.placement_hint.strip()
            if placement_hint and placement_hint in enriched:
                enriched = self._inject_near_hint(
                    enriched,
                    placement_hint=placement_hint,
                    reference=reference,
                    marker=marker,
                )
                continue

            enriched = self._append_to_section(
                enriched,
                section_name=entry.spec.section,
                reference=reference,
                marker=marker,
            )

        return enriched

    def _inject_near_hint(
        self,
        text: str,
        *,
        placement_hint: str,
        reference: str,
        marker: str,
    ) -> str:
        updated = text
        sentence_pattern = re.escape(placement_hint)
        match = re.search(sentence_pattern, updated)
        if not match:
            return updated

        sentence = match.group(0)
        if reference not in updated:
            updated_sentence = self._append_reference(sentence, reference)
            updated = updated[: match.start()] + updated_sentence + updated[match.end() :]

        paragraph_start = updated.rfind("\n\n", 0, match.end())
        paragraph_start = 0 if paragraph_start < 0 else paragraph_start + 2
        paragraph_end = updated.find("\n\n", match.end())
        paragraph_end = len(updated) if paragraph_end < 0 else paragraph_end
        paragraph = updated[paragraph_start:paragraph_end]
        if marker not in paragraph:
            paragraph = f"{paragraph.rstrip()}\n{marker}"
            updated = updated[:paragraph_start] + paragraph + updated[paragraph_end:]
        return updated

    def _append_to_section(self, text: str, *, section_name: str, reference: str, marker: str) -> str:
        pattern = _SECTION_HEADING_MAP.get(section_name)
        if pattern is None:
            return self._append_to_tail(text, reference=reference, marker=marker)

        match = pattern.search(text)
        if match is None:
            return self._append_to_tail(text, reference=reference, marker=marker)

        section_start = match.end()
        next_positions = [
            next_match.start()
            for key, next_pattern in _SECTION_HEADING_MAP.items()
            if key != section_name
            for next_match in [next_pattern.search(text, section_start)]
            if next_match is not None
        ]
        section_end = min(next_positions) if next_positions else len(text)
        section_body = text[section_start:section_end].rstrip()

        if reference not in section_body:
            section_body = f"{section_body}\n\n{reference}."
        if marker not in section_body:
            section_body = f"{section_body}\n{marker}"
        return text[:section_start] + section_body + text[section_end:]

    def _append_to_tail(self, text: str, *, reference: str, marker: str) -> str:
        updated = text.rstrip()
        if reference not in updated:
            updated = f"{updated}\n\n{reference}."
        if marker not in updated:
            updated = f"{updated}\n{marker}"
        return updated

    def _append_reference(self, sentence: str, reference: str) -> str:
        if reference in sentence or re.search(rf"\(see\s+{re.escape(reference)}\)", sentence):
            return sentence
        if sentence.rstrip().endswith("."):
            return re.sub(r"\.\s*$", f" (see {reference}).", sentence, count=1)
        return f"{sentence.rstrip()} (see {reference})"
