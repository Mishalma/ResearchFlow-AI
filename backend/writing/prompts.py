from __future__ import annotations

from dataclasses import dataclass

from structuring.schemas import SectionSkeleton
from writing.utils import ConfidencePhraseProfile


@dataclass(frozen=True)
class SectionPersona:
    name: str
    rhetorical_objective: str
    allowed_tone: str
    forbidden_patterns: tuple[str, ...]
    preferred_sentence_style: str
    evidence_usage_rules: str
    hedging_strategy: str


SECTION_PERSONAS: dict[str, SectionPersona] = {
    "abstract": SectionPersona(
        name="abstract",
        rhetorical_objective="Summarize the contribution, method, and outcome in one dense paragraph.",
        allowed_tone="concise, contribution-forward, formal",
        forbidden_patterns=("marketing hype", "unsupported novelty claims", "vague filler"),
        preferred_sentence_style="compact compound sentences with precise transitions",
        evidence_usage_rules="Mention only contribution and findings supported by the structured draft.",
        hedging_strategy="Use measured compression when evidence is incomplete.",
    ),
    "introduction": SectionPersona(
        name="introduction",
        rhetorical_objective="Frame the problem, motivation, gap, and contribution clearly.",
        allowed_tone="accessible, precise, scholarly",
        forbidden_patterns=("sweeping claims", "unbounded importance statements"),
        preferred_sentence_style="problem-to-gap-to-contribution progression",
        evidence_usage_rules="Ground the motivation and contribution in the provided evidence points.",
        hedging_strategy="Narrow the scope of claims when confidence is moderate or low.",
    ),
    "related_work": SectionPersona(
        name="related_work",
        rhetorical_objective="Contextualize prior work and position the current work neutrally.",
        allowed_tone="comparative, neutral, contextual",
        forbidden_patterns=("exaggerated novelty language", "dismissive treatment of prior work"),
        preferred_sentence_style="balanced comparative statements",
        evidence_usage_rules="Only discuss distinctions explicitly supported by the source material.",
        hedging_strategy="Use careful contrastive phrasing when evidence is indirect.",
    ),
    "methodology": SectionPersona(
        name="methodology",
        rhetorical_objective="Describe the procedure, setup, components, and workflow concretely.",
        allowed_tone="procedural, reproducible, concrete",
        forbidden_patterns=("vague adjectives", "persuasive flourish"),
        preferred_sentence_style="step-oriented operational prose",
        evidence_usage_rules="Prefer direct procedural evidence and avoid inventing implementation detail.",
        hedging_strategy="Signal missing operational detail explicitly rather than guessing.",
    ),
    "results": SectionPersona(
        name="results",
        rhetorical_objective="Present findings, metrics, or trends with evidence-first wording.",
        allowed_tone="measured, analytical, formal",
        forbidden_patterns=("overclaiming", "causal certainty without support"),
        preferred_sentence_style="finding-led statements followed by scope or condition",
        evidence_usage_rules="Separate observed findings from interpretation.",
        hedging_strategy="Use cautious reporting for sparse or indirect evidence.",
    ),
    "discussion": SectionPersona(
        name="discussion",
        rhetorical_objective="Interpret the meaning, implications, and trade-offs of the findings.",
        allowed_tone="interpretive, precise, reflective",
        forbidden_patterns=("new unsupported claims", "certainty inflation"),
        preferred_sentence_style="claim then interpretation with explicit assumptions",
        evidence_usage_rules="Keep interpretation linked to prior findings and state when it is inferential.",
        hedging_strategy="Mark inferences clearly and retain conditions on broader implications.",
    ),
    "limitations": SectionPersona(
        name="limitations",
        rhetorical_objective="State constraints, gaps, or threats to validity candidly.",
        allowed_tone="candid, bounded, precise",
        forbidden_patterns=("defensive spin", "minimizing weaknesses"),
        preferred_sentence_style="direct statements of constraint and impact",
        evidence_usage_rules="Surface weak coverage, assumptions, and missing data explicitly.",
        hedging_strategy="Do not soften genuine limitations into marketing language.",
    ),
    "conclusion": SectionPersona(
        name="conclusion",
        rhetorical_objective="Synthesize the contribution and close the paper without adding surprises.",
        allowed_tone="concise, synthesizing, formal",
        forbidden_patterns=("new claims", "sudden detail expansion"),
        preferred_sentence_style="high-level synthesis with restrained takeaway",
        evidence_usage_rules="Restate supported contribution and bounded takeaway only.",
        hedging_strategy="Maintain measured wording if the evidence base is limited.",
    ),
}


def build_section_prompt(
    *,
    section_name: str,
    persona: SectionPersona,
    skeleton: SectionSkeleton,
    confidence_profile: ConfidencePhraseProfile,
    paper_topic: str,
    paper_domain: str,
    writing_style_preferences: str,
) -> str:
    return (
        f"You are the Writing Agent for an IEEE paper generation pipeline.\n"
        f"Rewrite the {section_name.replace('_', ' ')} section into polished academic prose.\n\n"
        f"Rhetorical objective: {persona.rhetorical_objective}\n"
        f"Allowed tone: {persona.allowed_tone}\n"
        f"Forbidden patterns: {', '.join(persona.forbidden_patterns)}\n"
        f"Preferred sentence style: {persona.preferred_sentence_style}\n"
        f"Evidence usage rules: {persona.evidence_usage_rules}\n"
        f"Hedging strategy: {persona.hedging_strategy}\n"
        f"Confidence guidance: {confidence_profile.guidance}\n"
        f"Preferred evidence opener: {confidence_profile.evidence_lead}\n"
        f"Preferred inference opener: {confidence_profile.inference_lead}\n"
        f"Paper topic: {paper_topic or 'unspecified'}\n"
        f"Paper domain: {paper_domain or 'unspecified'}\n"
        f"Writing preferences: {writing_style_preferences or 'default formal IEEE prose'}\n\n"
        "Rules:\n"
        "- Do not invent citations, numbers, datasets, or results.\n"
        "- Do not silently turn uncertainty into certainty.\n"
        "- Keep the output to one well-structured paragraph.\n"
        "- Preserve the distinction between direct evidence and inference.\n"
        "- If evidence is limited, say so clearly and professionally.\n"
        "- Return JSON only.\n\n"
        f"Section skeleton JSON:\n{skeleton.model_dump_json(indent=2)}"
    )
