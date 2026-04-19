"""Robust perplexity scoring utilities for the humanizer runtime."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import List

from humanizer.config import PERPLEXITY_MIN_HUMAN_SCORE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerplexityMetric:
    """Compatibility wrapper for callers expecting a structured metric."""

    value: float
    available: bool
    model_name: str


class PerplexityScorer:
    """Score text perplexity using a local causal language model when available."""

    def __init__(self, model_name: str | object = "distilgpt2"):
        if hasattr(model_name, "perplexity_model_name"):
            resolved_model_name = str(
                getattr(model_name, "perplexity_model_name", "distilgpt2")
            )
        else:
            resolved_model_name = str(model_name or "distilgpt2")

        self.model_name = resolved_model_name
        self.available = False
        self._tokenizer = None
        self._model = None
        self._torch = None
        allow_download = os.getenv("HUMANIZER_ALLOW_MODEL_DOWNLOAD", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                resolved_model_name,
                local_files_only=not allow_download,
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                resolved_model_name,
                local_files_only=not allow_download,
            )
            self._model.eval()
            self._torch = torch
            self.available = True
        except Exception as exc:  # pragma: no cover - dependency/model dependent
            logger.warning(
                "Perplexity model '%s' is unavailable; disabling perplexity scoring: %s",
                model_name,
                exc,
            )

    def score(self, text: str) -> float | None:
        """Return perplexity for one text, or ``None`` if unavailable."""

        if not self.available:
            return None

        normalized = (text or "").strip()
        if not normalized:
            return None

        try:
            torch = self._torch
            assert torch is not None
            encoded = self._tokenizer(
                normalized,
                return_tensors="pt",
                truncation=False,
            )
            input_ids = encoded["input_ids"]
            max_length = min(
                getattr(self._model.config, "n_positions", 1024),
                1024,
            )
            stride = max(64, max_length // 2)
            negative_log_likelihood = 0.0
            token_count = 0
            previous_end = 0

            with torch.no_grad():
                for begin in range(0, input_ids.size(1), stride):
                    end = min(begin + max_length, input_ids.size(1))
                    target_length = end - previous_end
                    input_slice = input_ids[:, begin:end]
                    target_ids = input_slice.clone()
                    if target_length < target_ids.size(1):
                        target_ids[:, :-target_length] = -100
                    outputs = self._model(input_slice, labels=target_ids)
                    negative_log_likelihood += float(outputs.loss) * target_length
                    token_count += target_length
                    previous_end = end
                    if end >= input_ids.size(1):
                        break

            if token_count <= 0:
                return None
            perplexity = math.exp(negative_log_likelihood / token_count)
            return round(max(1.0, min(500.0, float(perplexity))), 4)
        except RuntimeError as exc:
            logger.warning("Perplexity scoring runtime error: %s", exc)
            return None
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Perplexity scoring failed: %s", exc)
            return None

    def score_batch(self, texts: List[str]) -> List[float | None]:
        """Return perplexity values for a batch of texts in the same order."""

        return [self.score(text) for text in texts]

    def is_human_like(self, text: str, threshold: float | None = None) -> bool | None:
        """Return whether the text clears the configured human-like perplexity threshold."""

        value = self.score(text)
        if value is None:
            return None
        resolved_threshold = threshold if threshold is not None else PERPLEXITY_MIN_HUMAN_SCORE
        return value >= resolved_threshold

    def score_text(self, text: str) -> PerplexityMetric:
        """Compatibility helper returning a structured metric."""

        value = self.score(text)
        return PerplexityMetric(
            value=float(value or 0.0),
            available=value is not None,
            model_name=self.model_name,
        )

    def score_paragraphs(self, text: str) -> list[PerplexityMetric]:
        """Compatibility helper returning paragraph-level metrics."""

        paragraphs = [paragraph.strip() for paragraph in (text or "").split("\n\n") if paragraph.strip()]
        return [self.score_text(paragraph) for paragraph in paragraphs]
