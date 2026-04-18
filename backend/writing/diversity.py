from __future__ import annotations

from dataclasses import dataclass

from writing.utils import HEDGING_MARKERS, split_sentences

VARIATION_MAP: dict[str, tuple[str, ...]] = {
    "the evidence suggests": (
        "The available evidence suggests",
        "The source material indicates",
        "The evidence further suggests",
    ),
    "the available evidence suggests": (
        "The evidence suggests",
        "The available material indicates",
    ),
    "this section": (
        "This discussion",
        "This analysis",
    ),
    "the results": (
        "These results",
        "The reported findings",
    ),
    "the methodology": (
        "The proposed methodology",
        "The procedural setup",
    ),
}


@dataclass(frozen=True)
class DiversityConstraints:
    preserve_numbers: bool = True
    preserve_quotes: bool = True
    preserve_hedging: bool = True
    confidence: float = 1.0


class DiversityRewriter:
    def rewrite(self, section_text: str, section_name: str, constraints: DiversityConstraints) -> str:
        raise NotImplementedError


class HeuristicDiversityRewriter(DiversityRewriter):
    def rewrite(self, section_text: str, section_name: str, constraints: DiversityConstraints) -> str:
        sentences = split_sentences(section_text)
        if len(sentences) < 2:
            return section_text

        rewritten: list[str] = []
        opener_counts: dict[str, int] = {}
        for sentence in sentences:
            rewritten.append(self._rewrite_sentence(sentence, opener_counts, constraints))
        return " ".join(rewritten).strip()

    def _rewrite_sentence(
        self,
        sentence: str,
        opener_counts: dict[str, int],
        constraints: DiversityConstraints,
    ) -> str:
        lowered = sentence.lower().strip()
        if constraints.preserve_numbers and any(character.isdigit() for character in sentence):
            return sentence
        if constraints.preserve_quotes and ('"' in sentence or "'" in sentence):
            return sentence
        if constraints.preserve_hedging and any(marker in lowered for marker in HEDGING_MARKERS) and constraints.confidence < 0.65:
            return sentence

        for prefix, alternatives in VARIATION_MAP.items():
            if lowered.startswith(prefix):
                opener_counts[prefix] = opener_counts.get(prefix, 0) + 1
                if opener_counts[prefix] <= 1:
                    return sentence
                replacement = alternatives[(opener_counts[prefix] - 2) % len(alternatives)]
                return replacement + sentence[len(prefix) :]
        return sentence


def apply_diversity_pass(
    section_text: str,
    section_name: str,
    constraints: DiversityConstraints,
    rewriter: DiversityRewriter | None = None,
) -> str:
    active_rewriter = rewriter or HeuristicDiversityRewriter()
    return active_rewriter.rewrite(section_text, section_name, constraints)
