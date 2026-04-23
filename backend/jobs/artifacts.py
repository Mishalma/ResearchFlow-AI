from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from core.config import get_settings
from models.generation import GeneratedPaper
from models.job import JobResultResponse, WorkflowArtifactPointer
from persistence import get_object_storage


def _job_prefix(project_id: str, job_id: str) -> str:
    return f"projects/{project_id}/jobs/{job_id}"


def build_extracted_text_key(project_id: str, job_id: str) -> str:
    return f"{_job_prefix(project_id, job_id)}/sources/extracted_text.json"


def build_draft_key(project_id: str, job_id: str, version: str) -> str:
    return f"{_job_prefix(project_id, job_id)}/drafts/{version}.json"


def build_final_report_key(project_id: str, job_id: str) -> str:
    return f"{_job_prefix(project_id, job_id)}/reports/final_report.json"


def build_final_accepted_draft_key(project_id: str, job_id: str) -> str:
    return f"{_job_prefix(project_id, job_id)}/reports/final_accepted_draft.json"


def build_validation_report_key(project_id: str, job_id: str, *, mode: str, revision: str = "v1") -> str:
    return f"{_job_prefix(project_id, job_id)}/metadata/validation_{mode}_{revision}.json"


def _normalize_payload(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="python")
    if isinstance(payload, dict):
        return {key: _normalize_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_normalize_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [_normalize_payload(item) for item in payload]
    if isinstance(payload, datetime):
        return payload.isoformat()
    return payload


def _write_json_temp_file(payload: Any) -> tuple[Path, str]:
    settings = get_settings()
    normalized_payload = _normalize_payload(payload)
    json_text = json.dumps(normalized_payload, indent=2, ensure_ascii=False)
    digest = hashlib.sha256(json_text.encode("utf-8")).hexdigest()
    temp_path = Path(
        NamedTemporaryFile(
            delete=False,
            dir=settings.temp_dir,
            prefix="workflow-artifact-",
            suffix=".json",
        ).name
    )
    temp_path.write_text(json_text, encoding="utf-8")
    return temp_path, digest


def store_json_artifact(
    *,
    key: str,
    payload: Any,
    owner_service: str,
    version: str,
) -> WorkflowArtifactPointer:
    object_storage = get_object_storage()
    temp_path, digest = _write_json_temp_file(payload)
    try:
        stored = object_storage.upload_file(key, temp_path, content_type="application/json")
    finally:
        temp_path.unlink(missing_ok=True)

    return WorkflowArtifactPointer(
        uri=stored.storage_uri,
        owner_service=owner_service,
        version=version,
        content_type=stored.content_type or "application/json",
        checksum_sha256=digest,
    )


def store_extracted_text_artifact(project_id: str, job_id: str, extracted_text: str) -> WorkflowArtifactPointer:
    return store_json_artifact(
        key=build_extracted_text_key(project_id, job_id),
        payload={"project_id": project_id, "extracted_text": extracted_text},
        owner_service="upload",
        version="extracted_text",
    )


def store_generated_draft_artifact(
    project_id: str,
    job_id: str,
    *,
    version: str,
    generated_paper: GeneratedPaper,
    owner_service: str = "generation-service",
) -> WorkflowArtifactPointer:
    return store_json_artifact(
        key=build_draft_key(project_id, job_id, version),
        payload=generated_paper,
        owner_service=owner_service,
        version=version,
    )


def store_final_accepted_draft_artifact(
    project_id: str,
    job_id: str,
    generated_paper: GeneratedPaper,
    *,
    owner_service: str = "finalize-service",
) -> WorkflowArtifactPointer:
    return store_json_artifact(
        key=build_final_accepted_draft_key(project_id, job_id),
        payload=generated_paper,
        owner_service=owner_service,
        version="final_accepted_draft",
    )


def store_job_result_report(
    project_id: str,
    job_id: str,
    result: JobResultResponse,
    *,
    owner_service: str = "finalize-service",
) -> WorkflowArtifactPointer:
    return store_json_artifact(
        key=build_final_report_key(project_id, job_id),
        payload=result,
        owner_service=owner_service,
        version="final_report",
    )


def store_validation_report_artifact(
    project_id: str,
    job_id: str,
    report: Any,
    *,
    mode: str,
    revision: str = "v1",
    owner_service: str = "validation-service",
) -> WorkflowArtifactPointer:
    return store_json_artifact(
        key=build_validation_report_key(project_id, job_id, mode=mode, revision=revision),
        payload=report,
        owner_service=owner_service,
        version=f"validation_{mode}_{revision}",
    )


def artifact_uri_to_key(uri: str) -> str:
    normalized = str(uri or "").strip()
    if not normalized:
        raise ValueError("Artifact URI is required.")

    settings = get_settings()
    if normalized.startswith("gs://"):
        expected_prefix = f"gs://{settings.gcs_bucket_name}/" if settings.gcs_bucket_name else ""
        if expected_prefix and normalized.startswith(expected_prefix):
            return normalized[len(expected_prefix) :]
        match = re.match(r"^gs://[^/]+/(.+)$", normalized)
        if match:
            return match.group(1)
        raise ValueError(f"Unsupported Cloud Storage URI '{normalized}'.")

    path = Path(normalized)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(settings.base_dir.resolve()).as_posix()
        except ValueError:
            return path.name

    return normalized.replace("\\", "/")


def load_json_artifact_from_uri(uri: str) -> Any:
    object_storage = get_object_storage()
    downloaded = object_storage.download_bytes(artifact_uri_to_key(uri))
    return json.loads(downloaded.content.decode("utf-8"))


def load_generated_draft_artifact(uri: str) -> GeneratedPaper:
    payload = load_json_artifact_from_uri(uri)
    return GeneratedPaper.model_validate(payload)


def load_extracted_text_artifact(uri: str) -> str:
    payload = load_json_artifact_from_uri(uri)
    if isinstance(payload, dict):
        extracted_text = str(payload.get("extracted_text") or "").strip()
        if extracted_text:
            return extracted_text
    return str(payload or "").strip()


def load_job_result_report(project_id: str, job_id: str) -> JobResultResponse:
    object_storage = get_object_storage()
    downloaded = object_storage.download_bytes(build_final_report_key(project_id, job_id))
    payload = json.loads(downloaded.content.decode("utf-8"))
    return JobResultResponse.model_validate(payload)
