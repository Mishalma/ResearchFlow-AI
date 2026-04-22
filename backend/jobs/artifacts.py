from __future__ import annotations

import hashlib
import json
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


def load_job_result_report(project_id: str, job_id: str) -> JobResultResponse:
    object_storage = get_object_storage()
    downloaded = object_storage.download_bytes(build_final_report_key(project_id, job_id))
    payload = json.loads(downloaded.content.decode("utf-8"))
    return JobResultResponse.model_validate(payload)
