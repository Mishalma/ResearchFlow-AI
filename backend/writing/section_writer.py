from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from core.exceptions import GenerationError
from core.vertex_client import VertexGeminiClient
from structuring.schemas import SectionSkeleton, StructuredPaperDraft
from writing.config import WritingConfig
from writing.diversity import DiversityConstraints, DiversityRewriter, HeuristicDiversityRewriter, apply_diversity_pass
from writing.prompts import SECTION_PERSONAS, SectionPersona, build_section_prompt
from writing.schemas import BODY_WRITING_SECTIONS, WrittenPaperDraft, WrittenSection
from writing.utils import (
    AnnotationBundle,
    annotate_section_text,
    compute_global_confidence,
    confidence_profile,
    derive_keywords,
    score_title_candidate,
    summarize_annotations,
)

logger = logging.getLogger("papereasy.backend.writing.section_writer")


class SectionGenerationResponse(BaseModel):
    text: str = ""
    revision_notes: list[str] = Field(default_factory=list)

    @field_validator("revision_notes", mode="before")
    @classmethod
    def normalize_revision_notes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


class TitleGenerationResponse(BaseModel):
    title: str = Field(min_length=1)
    revision_notes: list[str] = Field(default_factory=list)

    @field_validator("revision_notes", mode="before")
    @classmethod
    def normalize_revision_notes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = list(value)
        return [str(item).strip() for item in candidates if str(item).strip()]


@dataclass(frozen=True)
class SectionGenerationResult:
    text: str
    revision_notes: list[str]
    backend: str


class BaseSectionGenerator(Protocol):
    async def generate_section(
        self,
        *,
        section_name: str,
        skeleton: SectionSkeleton,
        persona: SectionPersona,
        context: dict[str, str],
    ) -> SectionGenerationResult:
        ...


class LLMSectionGenerator:
    def __init__(
        self,
        *,
        client: VertexGeminiClient,
        config: WritingConfig,
    ):
        self.client = client
        self.config = config

    async def generate_section(
        self,
        *,
        section_name: str,
        skeleton: SectionSkeleton,
        persona: SectionPersona,
        context: dict[str, str],
    ) -> SectionGenerationResult:
        prompt = build_section_prompt(
            section_name=section_name,
            persona=persona,
            skeleton=skeleton,
            confidence_profile=confidence_profile(
                skeleton.confidence,
                low_threshold=self.config.low_confidence_threshold,
                medium_threshold=self.config.medium_confidence_threshold,
                high_threshold=self.config.high_confidence_threshold,
            ),
            paper_topic=context.get("paper_topic", ""),
            paper_domain=context.get("paper_domain", ""),
            writing_style_preferences=context.get("writing_style_preferences", ""),
        )
        response = await self.client.generate_json(
            prompt=prompt,
            response_schema=SectionGenerationResponse,
            model_name=self.config.reducer_model,
        )
        return SectionGenerationResult(
            text=response.text.strip(),
            revision_notes=response.revision_notes,
            backend="vertex",
        )


class DeterministicSectionGenerator:
    async def generate_section(
        self,
        *,
        section_name: str,
        skeleton: SectionSkeleton,
        persona: SectionPersona,
        context: dict[str, str],
    ) -> SectionGenerationResult:
        config = context["config"]
        profile = confidence_profile(
            skeleton.confidence,
            low_threshold=config.low_confidence_threshold,
            medium_threshold=config.medium_confidence_threshold,
            high_threshold=config.high_confidence_threshold,
        )
        text = _compose_section_text(
            section_name=section_name,
            skeleton=skeleton,
            persona=persona,
            profile=profile,
            sentence_limit=config.section_sentence_limits.get(section_name, 5),
        )
        return SectionGenerationResult(
            text=text,
            revision_notes=["Generated via deterministic fallback."],
            backend="deterministic",
        )


async def write_paper(
    *,
    structured_draft: StructuredPaperDraft,
    config: WritingConfig,
    vertex_client: VertexGeminiClient,
    paper_topic: str,
    paper_domain: str,
    author_metadata: str,
    writing_style_preferences: str,
    trace_id: str,
    fallback_keywords: list[str] | None = None,
    fallback_references: list[str] | None = None,
    logger_: logging.Logger | None = None,
) -> tuple[WrittenPaperDraft, dict[str, float], dict[str, int], str]:
    active_logger = logger_ or logger
    llm_generator = LLMSectionGenerator(client=vertex_client, config=config) if config.use_model_generator else None
    deterministic_generator = DeterministicSectionGenerator()
    diversity_rewriter: DiversityRewriter | None = HeuristicDiversityRewriter() if config.enable_diversity_pass else None

    context = {
        "paper_topic": paper_topic,
        "paper_domain": paper_domain,
        "author_metadata": author_metadata,
        "writing_style_preferences": writing_style_preferences,
        "config": config,
    }

    section_semaphore = asyncio.Semaphore(config.max_parallel_section_writes)
    title_task = asyncio.create_task(
        select_title(
            structured_draft=structured_draft,
            config=config,
            vertex_client=vertex_client,
            paper_topic=paper_topic,
            paper_domain=paper_domain,
        )
    )
    section_tasks = {
        section_name: asyncio.create_task(
            _write_section_with_semaphore(
                section_name=section_name,
                skeleton=structured_draft.sections[section_name],
                config=config,
                context=context,
                llm_generator=llm_generator,
                deterministic_generator=deterministic_generator,
                diversity_rewriter=diversity_rewriter,
                semaphore=section_semaphore,
            )
        )
        for section_name in ("abstract", *BODY_WRITING_SECTIONS)
    }

    title, title_notes, title_backend = await title_task
    active_logger.info("Writing trace %s selected title via %s.", trace_id, title_backend)

    abstract_section, abstract_bundle, abstract_backend = await section_tasks["abstract"]

    body_sections: dict[str, WrittenSection] = {}
    annotation_bundles: dict[str, AnnotationBundle] = {}
    generation_backends: dict[str, str] = {"title": title_backend, "abstract": abstract_backend}
    for section_name in BODY_WRITING_SECTIONS:
        written_section, annotation_bundle, backend_name = await section_tasks[section_name]
        body_sections[section_name] = written_section
        annotation_bundles[section_name] = annotation_bundle
        generation_backends[section_name] = backend_name

    section_confidences = {
        "abstract": abstract_section.confidence,
        **{section_name: section.confidence for section_name, section in body_sections.items()},
    }
    annotation_summary = summarize_annotations(
        abstract_bundle=abstract_bundle,
        section_bundles=annotation_bundles,
    )
    keywords = derive_keywords(
        title=title,
        abstract_text=abstract_section.text,
        section_texts=[section.text for section in body_sections.values()],
        paper_domain=paper_domain,
        fallback_keywords=fallback_keywords,
    )
    written_draft = WrittenPaperDraft(
        title=title,
        abstract=abstract_section,
        sections=body_sections,
        global_confidence=compute_global_confidence(section_confidences.values()),
        metadata={
            "trace_id": trace_id,
            "title_notes": title_notes,
            "generation_backends": generation_backends,
            "keywords": keywords,
            "annotation_summary": annotation_summary,
            "fallback_references": list(fallback_references or []),
        },
    )
    return written_draft, section_confidences, annotation_summary, title_backend


async def write_section(
    *,
    section_name: str,
    skeleton: SectionSkeleton,
    config: WritingConfig,
    context: dict[str, object],
    llm_generator: LLMSectionGenerator | None,
    deterministic_generator: DeterministicSectionGenerator,
    diversity_rewriter: DiversityRewriter | None,
) -> tuple[WrittenSection, AnnotationBundle, str]:
    persona = SECTION_PERSONAS[section_name]
    revision_notes: list[str] = []
    generation_result: SectionGenerationResult | None = None

    if llm_generator is not None:
        try:
            generation_result = await llm_generator.generate_section(
                section_name=section_name,
                skeleton=skeleton,
                persona=persona,
                context={
                    "paper_topic": str(context.get("paper_topic", "")),
                    "paper_domain": str(context.get("paper_domain", "")),
                    "writing_style_preferences": str(context.get("writing_style_preferences", "")),
                },
            )
        except Exception as exc:
            revision_notes.append(f"Vertex generation failed; deterministic fallback used. Detail: {exc}")
            logger.warning("Writing section %s fell back to deterministic generation: %s", section_name, exc)

    if generation_result is None:
        generation_result = await deterministic_generator.generate_section(
            section_name=section_name,
            skeleton=skeleton,
            persona=persona,
            context=context,
        )

    revision_notes.extend(generation_result.revision_notes)
    section_text = generation_result.text.strip()
    if not section_text:
        section_text = _compose_section_text(
            section_name=section_name,
            skeleton=skeleton,
            persona=persona,
            profile=confidence_profile(
                skeleton.confidence,
                low_threshold=config.low_confidence_threshold,
                medium_threshold=config.medium_confidence_threshold,
                high_threshold=config.high_confidence_threshold,
            ),
            sentence_limit=config.section_sentence_limits.get(section_name, 5),
        )
        revision_notes.append("Generated fallback prose because the initial section text was empty.")

    if diversity_rewriter is not None:
        section_text = apply_diversity_pass(
            section_text,
            section_name,
            DiversityConstraints(
                confidence=skeleton.confidence,
                preserve_hedging=True,
            ),
            rewriter=diversity_rewriter,
        )
        revision_notes.append("Applied deterministic diversity pass.")

    annotation_bundle = annotate_section_text(
        text=section_text,
        section_name=section_name,
        confidence=skeleton.confidence,
        skeleton=skeleton,
    )
    final_confidence = _adjust_confidence_for_annotations(skeleton.confidence, annotation_bundle)
    written_section = WrittenSection(
        section_name=section_name,
        text=section_text,
        confidence=final_confidence,
        claims=annotation_bundle.claims,
        evidence_backed_sentences=annotation_bundle.evidence_backed_sentences,
        inferred_sentences=annotation_bundle.inferred_sentences,
        hedged_sentences=annotation_bundle.hedged_sentences,
        unsupported_sentences=annotation_bundle.unsupported_sentences,
        used_source_spans=annotation_bundle.used_source_spans,
        revision_notes=revision_notes,
    )
    return written_section, annotation_bundle, generation_result.backend


async def _write_section_with_semaphore(
    *,
    section_name: str,
    skeleton: SectionSkeleton,
    config: WritingConfig,
    context: dict[str, object],
    llm_generator: LLMSectionGenerator | None,
    deterministic_generator: DeterministicSectionGenerator,
    diversity_rewriter: DiversityRewriter | None,
    semaphore: asyncio.Semaphore,
) -> tuple[WrittenSection, AnnotationBundle, str]:
    async with semaphore:
        return await write_section(
            section_name=section_name,
            skeleton=skeleton,
            config=config,
            context=context,
            llm_generator=llm_generator,
            deterministic_generator=deterministic_generator,
            diversity_rewriter=diversity_rewriter,
        )


async def select_title(
    *,
    structured_draft: StructuredPaperDraft,
    config: WritingConfig,
    vertex_client: VertexGeminiClient,
    paper_topic: str,
    paper_domain: str,
) -> tuple[str, list[str], str]:
    scored_candidates = sorted(
        (
            (
                score_title_candidate(
                    candidate,
                    structured_draft=structured_draft,
                    paper_topic=paper_topic,
                    paper_domain=paper_domain,
                    max_words=config.preferred_title_max_words,
                ),
                candidate,
            )
            for candidate in structured_draft.title_candidates
        ),
        reverse=True,
    )

    if config.use_model_generator and scored_candidates:
        try:
            notes = [
                f"{candidate} (score={score})"
                for score, candidate in scored_candidates[:3]
            ]
            prompt = (
                "You are the Writing Agent title selector for an IEEE paper pipeline.\n"
                "Choose or refine a specific, descriptive, non-sensational title.\n"
                "Return JSON only.\n"
                "Do not invent claims beyond the supplied candidates and evidence summary.\n\n"
                f"Paper topic: {paper_topic or 'unspecified'}\n"
                f"Paper domain: {paper_domain or 'unspecified'}\n"
                f"Candidate titles:\n- " + "\n- ".join(notes) + "\n\n"
                f"Evidence summary:\n{structured_draft.sections['introduction'].draft}\n"
                f"{structured_draft.sections['methodology'].draft}\n"
                f"{structured_draft.sections['results'].draft}"
            )
            response = await vertex_client.generate_json(
                prompt=prompt,
                response_schema=TitleGenerationResponse,
                model_name=config.reducer_model,
            )
            return response.title.strip(), response.revision_notes, "vertex"
        except GenerationError as exc:
            logger.warning("Vertex title selection failed; falling back deterministically: %s", exc)
        except Exception as exc:
            logger.warning("Title selection failed; falling back deterministically: %s", exc)

    if scored_candidates:
        return scored_candidates[0][1].strip(), ["Selected best existing title candidate deterministically."], "deterministic"

    derived_title = " ".join(
        word.title()
        for word in (
            paper_topic
            or structured_draft.sections["introduction"].draft
            or structured_draft.sections["methodology"].draft
        ).split()[: config.preferred_title_max_words]
    ).strip()
    return derived_title or "IEEE Research Paper Draft", ["Derived title from structured draft content."], "deterministic"


def _compose_section_text(
    *,
    section_name: str,
    skeleton: SectionSkeleton,
    persona: SectionPersona,
    profile,
    sentence_limit: int,
) -> str:
    sentences: list[str] = []

    primary_points = skeleton.key_points or [skeleton.draft] if skeleton.draft else []
    direct_evidence = skeleton.direct_evidence or primary_points[:2]
    inferred = skeleton.inferred_synthesis[:1]
    missing = skeleton.missing_evidence[:1]

    if direct_evidence:
        lead = profile.evidence_lead
        sentences.append(_clean_sentence(f"{lead} that {direct_evidence[0]}."))
        for point in direct_evidence[1:2]:
            sentences.append(_clean_sentence(point))
    elif skeleton.draft:
        sentences.append(_clean_sentence(skeleton.draft))
    else:
        sentences.append(_clean_sentence(f"{profile.evidence_lead} this section remains incompletely supported by the available material."))

    if inferred:
        sentences.append(_clean_sentence(f"{profile.inference_lead.lower().capitalize()} that {inferred[0]}."))
    elif primary_points[1:2]:
        sentences.append(_clean_sentence(primary_points[1]))

    if missing:
        lead = profile.limitation_lead
        if section_name == "limitations":
            sentences.append(_clean_sentence(f"{lead} {missing[0]}."))
        elif skeleton.confidence < 0.65:
            sentences.append(_clean_sentence(f"{lead} {missing[0].lower()}."))

    bounded = []
    for sentence in sentences:
        if sentence and sentence not in bounded:
            bounded.append(sentence)
        if len(bounded) >= sentence_limit:
            break
    return " ".join(bounded).strip()


def _clean_sentence(sentence: str) -> str:
    normalized = " ".join(sentence.replace("\n", " ").split()).strip()
    if not normalized:
        return ""
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def _adjust_confidence_for_annotations(confidence: float, annotations: AnnotationBundle) -> float:
    penalty = min(len(annotations.unsupported_sentences) * 0.08, 0.3)
    bonus = min(len(annotations.evidence_backed_sentences) * 0.01, 0.05)
    return round(max(0.0, min(1.0, confidence - penalty + bonus)), 4)
