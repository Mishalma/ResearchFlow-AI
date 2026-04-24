from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from validation.config import ValidationConfig

logger = logging.getLogger("papereasy.validation.desklib_detector")

_GCS_URI_PATTERN = re.compile(r"^gs://([^/]+)(?:/(.*))?$")
_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
_TOKENIZER_FILES = (
    "tokenizer.json",
    "spm.model",
    "sentencepiece.bpe.model",
    "tokenizer.model",
    "vocab.json",
)


class DesklibDetectorError(RuntimeError):
    """Raised when the Desklib detector cannot be loaded or used."""


@dataclass(frozen=True)
class DesklibPrediction:
    score: float
    model_id: str
    device: str
    window_count: int
    batch_size: int

    def as_metadata(self) -> dict[str, float | int | str]:
        return {
            "ai_detector_backend": "desklib",
            "ai_detector_model_id": self.model_id,
            "ai_detector_device": self.device,
            "ai_detector_window_count": self.window_count,
            "ai_detector_batch_size": self.batch_size,
            "desklib_probability": self.score,
        }


def _has_required_model_files(model_path: Path) -> bool:
    if not model_path.exists() or not model_path.is_dir():
        return False
    has_config = (model_path / "config.json").is_file()
    has_weights = any((model_path / filename).is_file() for filename in _WEIGHT_FILES)
    has_tokenizer = any((model_path / filename).is_file() for filename in _TOKENIZER_FILES)
    return has_config and has_weights and has_tokenizer


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    match = _GCS_URI_PATTERN.match(gcs_uri.strip())
    if not match:
        raise DesklibDetectorError(
            f"AI_DETECTOR_MODEL_GCS_URI must be a gs:// URI, got '{gcs_uri}'."
        )
    bucket_name = match.group(1)
    prefix = (match.group(2) or "").strip("/")
    return bucket_name, prefix


def _sync_gcs_prefix_to_local(
    *,
    gcs_uri: str,
    destination: Path,
    project_id: str,
) -> None:
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DesklibDetectorError(
            "google-cloud-storage is required to load the Desklib model from GCS."
        ) from exc

    bucket_name, prefix = _parse_gcs_uri(gcs_uri)
    list_prefix = f"{prefix}/" if prefix else ""
    client = storage.Client(project=project_id or None)
    blobs = list(client.list_blobs(bucket_name, prefix=list_prefix))
    if not blobs:
        raise DesklibDetectorError(
            f"No model artifact files were found under '{gcs_uri}'."
        )

    destination.mkdir(parents=True, exist_ok=True)
    downloaded_count = 0
    for blob in blobs:
        if blob.name.endswith("/"):
            continue
        if list_prefix and blob.name.startswith(list_prefix):
            relative_name = blob.name[len(list_prefix) :]
        else:
            relative_name = Path(blob.name).name
        if not relative_name:
            continue

        target_path = destination / Path(relative_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target_path))
        downloaded_count += 1

    if downloaded_count == 0:
        raise DesklibDetectorError(
            f"No downloadable model files were found under '{gcs_uri}'."
        )


def ensure_desklib_model_available(
    config: ValidationConfig,
    *,
    project_id: str = "",
) -> Path:
    model_path = config.ai_detector_model_path
    if _has_required_model_files(model_path):
        return model_path

    if config.ai_detector_model_gcs_uri:
        logger.info(
            "Syncing Desklib detector artifacts from %s to %s",
            config.ai_detector_model_gcs_uri,
            model_path,
        )
        _sync_gcs_prefix_to_local(
            gcs_uri=config.ai_detector_model_gcs_uri,
            destination=model_path,
            project_id=project_id,
        )
        if _has_required_model_files(model_path):
            return model_path

    raise DesklibDetectorError(
        "Desklib AI detector artifacts are missing or incomplete. "
        "Set AI_DETECTOR_MODEL_PATH to a local Hugging Face snapshot or "
        "AI_DETECTOR_MODEL_GCS_URI to a GCS prefix containing config, tokenizer, and weights."
    )


def _build_model_class():
    import torch
    import torch.nn as nn
    from transformers import AutoConfig, AutoModel, PreTrainedModel

    class DesklibAIDetectionModel(PreTrainedModel):
        config_class = AutoConfig
        base_model_prefix = "model"
        _tied_weights_keys: list[str] = []
        all_tied_weights_keys: dict[str, set[str]] = {}

        def __init__(self, config):
            super().__init__(config)
            self.model = AutoModel.from_config(config)
            self.classifier = nn.Linear(config.hidden_size, 1)
            self.init_weights()

        def forward(self, input_ids, attention_mask=None, labels=None):
            outputs = self.model(input_ids, attention_mask=attention_mask)
            last_hidden_state = outputs[0]
            input_mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
            sum_embeddings = torch.sum(last_hidden_state * input_mask_expanded, dim=1)
            sum_mask = torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)
            pooled_output = sum_embeddings / sum_mask
            logits = self.classifier(pooled_output)
            return {"logits": logits}

    return DesklibAIDetectionModel


def _resolve_device(requested_device: str):
    import torch

    normalized = (requested_device or "auto").strip().lower()
    if normalized == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if normalized.startswith("cuda") and not torch.cuda.is_available():
        raise DesklibDetectorError(
            f"AI_DETECTOR_DEVICE={requested_device} was requested, but CUDA is not available."
        )
    if normalized not in {"cpu"} and not normalized.startswith("cuda"):
        raise DesklibDetectorError(
            "AI_DETECTOR_DEVICE must be 'auto', 'cpu', or a CUDA device such as 'cuda'."
        )
    return torch.device(normalized)


class DesklibDetector:
    def __init__(
        self,
        *,
        config: ValidationConfig,
        project_id: str = "",
    ):
        import torch
        from transformers import AutoConfig, AutoTokenizer

        self._config = config
        self._model_path = ensure_desklib_model_available(config, project_id=project_id)
        self._device = _resolve_device(config.ai_detector_device)
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self._model_path),
            local_files_only=True,
        )
        model_config = AutoConfig.from_pretrained(
            str(self._model_path),
            local_files_only=True,
        )
        model_class = _build_model_class()
        self._model = model_class.from_pretrained(
            str(self._model_path),
            config=model_config,
            local_files_only=True,
        )
        self._model.to(self._device)
        self._model.eval()
        self._torch = torch
        logger.info(
            "Loaded Desklib AI detector %s from %s on %s",
            config.ai_detector_model_id,
            self._model_path,
            self._device,
        )

    @property
    def device_name(self) -> str:
        return str(self._device)

    def _window_text(self, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []

        encoded = self._tokenizer(
            normalized,
            add_special_tokens=False,
            truncation=False,
        )
        token_ids = list(encoded.get("input_ids") or [])
        content_length = max(1, self._config.ai_detector_max_length - 2)
        if len(token_ids) <= content_length:
            return [normalized]

        stride = min(self._config.ai_detector_window_stride, content_length - 1)
        step = max(1, content_length - stride)
        windows: list[str] = []
        for start in range(0, len(token_ids), step):
            chunk = token_ids[start : start + content_length]
            if not chunk:
                continue
            decoded = self._tokenizer.decode(chunk, skip_special_tokens=True).strip()
            if decoded:
                windows.append(decoded)
            if start + content_length >= len(token_ids):
                break
        return windows or [normalized]

    def _score_batch(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self._config.ai_detector_max_length,
            return_tensors="pt",
        )
        encoded = {key: value.to(self._device) for key, value in encoded.items()}
        with self._torch.inference_mode():
            outputs = self._model(
                input_ids=encoded["input_ids"],
                attention_mask=encoded.get("attention_mask"),
            )
            logits = outputs["logits"].view(-1)
            probabilities = self._torch.sigmoid(logits).detach().cpu().tolist()
        return [round(max(0.0, min(1.0, float(score))), 4) for score in probabilities]

    def score_text(self, text: str) -> DesklibPrediction:
        windows = self._window_text(text)
        if not windows:
            return DesklibPrediction(
                score=0.0,
                model_id=self._config.ai_detector_model_id,
                device=self.device_name,
                window_count=0,
                batch_size=self._config.ai_detector_batch_size,
            )

        scores: list[float] = []
        batch_size = self._config.ai_detector_batch_size
        for index in range(0, len(windows), batch_size):
            scores.extend(self._score_batch(windows[index : index + batch_size]))

        score = max(scores) if scores else 0.0
        return DesklibPrediction(
            score=score,
            model_id=self._config.ai_detector_model_id,
            device=self.device_name,
            window_count=len(windows),
            batch_size=batch_size,
        )


_DETECTOR: DesklibDetector | None = None
_DETECTOR_KEY: tuple[object, ...] | None = None


def _config_key(config: ValidationConfig) -> tuple[object, ...]:
    return (
        config.ai_detector_model_id,
        str(config.ai_detector_model_path),
        config.ai_detector_model_gcs_uri,
        config.ai_detector_max_length,
        config.ai_detector_batch_size,
        config.ai_detector_device,
        config.ai_detector_window_stride,
    )


def get_desklib_detector(
    config: ValidationConfig,
    *,
    project_id: str = "",
) -> DesklibDetector:
    global _DETECTOR, _DETECTOR_KEY
    key = _config_key(config)
    if _DETECTOR is not None and _DETECTOR_KEY == key:
        return _DETECTOR
    _DETECTOR = DesklibDetector(config=config, project_id=project_id)
    _DETECTOR_KEY = key
    return _DETECTOR


def warm_desklib_detector(
    config: ValidationConfig,
    *,
    project_id: str = "",
) -> None:
    if config.ai_detector_backend != "desklib":
        return
    get_desklib_detector(config, project_id=project_id)


def reset_desklib_detector_for_tests() -> None:
    global _DETECTOR, _DETECTOR_KEY
    _DETECTOR = None
    _DETECTOR_KEY = None
