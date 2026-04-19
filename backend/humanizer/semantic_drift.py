"""Semantic drift detection for proposed humanizer rewrites."""

from __future__ import annotations

import logging
import os

import numpy as np

from humanizer.config import SEMANTIC_DRIFT_THRESHOLD

logger = logging.getLogger(__name__)


class SemanticDriftChecker:
    """Check whether a rewrite drifts too far from the original meaning."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.available = False
        self._model = None
        allow_download = os.getenv("HUMANIZER_ALLOW_MODEL_DOWNLOAD", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                model_name,
                local_files_only=not allow_download,
            )
            self.available = True
        except Exception as exc:  # pragma: no cover - dependency/model dependent
            logger.warning(
                "Semantic drift model '%s' is unavailable; drift checks will be optimistic: %s",
                model_name,
                exc,
            )

    def drift(self, original: str, rewritten: str) -> float | None:
        """Return semantic drift in [0.0, 1.0], or ``None`` if unavailable."""

        if not self.available or self._model is None:
            return None

        try:
            embeddings = self._model.encode([original or "", rewritten or ""])
            original_vector = np.asarray(embeddings[0], dtype=float)
            rewritten_vector = np.asarray(embeddings[1], dtype=float)
            denom = np.linalg.norm(original_vector) * np.linalg.norm(rewritten_vector)
            if denom == 0:
                return 0.0
            cosine_similarity = float(np.dot(original_vector, rewritten_vector) / denom)
            drift_score = 1.0 - max(-1.0, min(1.0, cosine_similarity))
            return round(max(0.0, min(1.0, drift_score)), 4)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Semantic drift scoring failed: %s", exc)
            return None

    def is_safe(
        self,
        original: str,
        rewritten: str,
        threshold: float | None = None,
    ) -> bool:
        """Return True when the rewrite is semantically safe."""

        drift_value = self.drift(original, rewritten)
        if drift_value is None:
            return True
        resolved_threshold = threshold if threshold is not None else SEMANTIC_DRIFT_THRESHOLD
        return drift_value <= resolved_threshold
