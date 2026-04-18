from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache

from humanizer.config import HumanizerConfig
from humanizer.utils import split_paragraphs

logger = logging.getLogger("papereasy.backend.humanizer.perplexity")


@dataclass(frozen=True)
class PerplexityMetric:
    value: float
    available: bool
    model_name: str


class PerplexityScorer:
    def __init__(self, config: HumanizerConfig):
        self.config = config

    def score_text(self, text: str) -> PerplexityMetric:
        if not self.config.enable_perplexity:
            return PerplexityMetric(value=0.0, available=False, model_name=self.config.perplexity_model_name)
        normalized = text.strip()
        if not normalized:
            return PerplexityMetric(value=0.0, available=False, model_name=self.config.perplexity_model_name)

        resources = _load_resources(
            self.config.perplexity_model_name,
            self.config.model_local_files_only,
        )
        if resources is None:
            return PerplexityMetric(value=0.0, available=False, model_name=self.config.perplexity_model_name)

        tokenizer, model, torch = resources
        encodings = tokenizer(
            normalized,
            return_tensors="pt",
            truncation=False,
        )
        input_ids = encodings["input_ids"]
        sequence_length = input_ids.size(1)
        max_length = self.config.perplexity_chunk_tokens
        stride = self.config.perplexity_stride_tokens
        negative_log_likelihoods: list[float] = []
        previous_end = 0

        with torch.no_grad():
            for begin in range(0, sequence_length, stride):
                end = min(begin + max_length, sequence_length)
                target_length = end - previous_end
                input_slice = input_ids[:, begin:end]
                target_ids = input_slice.clone()
                if target_length < target_ids.size(1):
                    target_ids[:, :-target_length] = -100
                outputs = model(input_slice, labels=target_ids)
                negative_log_likelihoods.append(float(outputs.loss) * target_length)
                previous_end = end
                if end >= sequence_length:
                    break

        token_count = max(sequence_length - 1, 1)
        perplexity = math.exp(sum(negative_log_likelihoods) / token_count)
        return PerplexityMetric(
            value=round(float(perplexity), 4),
            available=True,
            model_name=self.config.perplexity_model_name,
        )

    def score_paragraphs(self, text: str) -> list[PerplexityMetric]:
        paragraphs = split_paragraphs(text)
        return [self.score_text(paragraph) for paragraph in paragraphs]


@lru_cache(maxsize=2)
def _load_resources(model_name: str, local_files_only: bool):
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        logger.warning("transformers/torch unavailable for perplexity scoring: %s", exc)
        return None

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=local_files_only)
        model = AutoModelForCausalLM.from_pretrained(model_name, local_files_only=local_files_only)
        model.eval()
        return tokenizer, model, torch
    except Exception as exc:
        logger.warning("Unable to load perplexity model '%s': %s", model_name, exc)
        return None
