from __future__ import annotations

import argparse
import re
from pathlib import Path

_GCS_URI_PATTERN = re.compile(r"^gs://([^/]+)(?:/(.*))?$")


def _parse_gcs_uri(value: str) -> tuple[str, str]:
    match = _GCS_URI_PATTERN.match(value.strip())
    if not match:
        raise ValueError("--gcs-uri must be a gs:// bucket prefix.")
    return match.group(1), (match.group(2) or "").strip("/")


def _iter_model_files(model_dir: Path):
    for path in model_dir.rglob("*"):
        if not path.is_file():
            continue
        if ".cache" in path.parts:
            continue
        yield path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mirror the Desklib academic AI detector snapshot into GCS.",
    )
    parser.add_argument(
        "--model-id",
        default="desklib/ai-text-detector-academic-v1.01",
        help="Hugging Face model id to snapshot.",
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="Optional pinned Hugging Face revision or commit SHA.",
    )
    parser.add_argument(
        "--local-dir",
        default=".model-cache/desklib-ai-text-detector-academic-v1.01",
        help="Local cache directory for the downloaded snapshot.",
    )
    parser.add_argument(
        "--gcs-uri",
        required=True,
        help="Destination prefix, for example gs://bucket/models/desklib/ai-text-detector-academic-v1.01.",
    )
    args = parser.parse_args()

    from google.cloud import storage
    from huggingface_hub import snapshot_download

    local_dir = Path(args.local_dir).expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=args.model_id,
        revision=args.revision,
        local_dir=str(local_dir),
        allow_patterns=[
            "*.json",
            "*.safetensors",
            "*.model",
            "*.txt",
            "tokenizer*",
            "spm.model",
            "special_tokens_map.json",
        ],
    )

    bucket_name, prefix = _parse_gcs_uri(args.gcs_uri)
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    uploaded = 0
    for path in _iter_model_files(local_dir):
        relative_path = path.relative_to(local_dir).as_posix()
        blob_name = f"{prefix}/{relative_path}" if prefix else relative_path
        bucket.blob(blob_name).upload_from_filename(str(path))
        uploaded += 1

    print(f"Uploaded {uploaded} model files to gs://{bucket_name}/{prefix}".rstrip("/"))


if __name__ == "__main__":
    main()
