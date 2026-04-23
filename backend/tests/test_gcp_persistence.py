from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.exceptions import PersistenceError
from persistence.gcp import GCSObjectStorage


class _FailingBlob:
    def __init__(self, message: str):
        self._message = message

    def upload_from_filename(self, *_args, **_kwargs):
        raise RuntimeError(self._message)


class _Bucket:
    def __init__(self, name: str, message: str):
        self.name = name
        self._message = message

    def blob(self, _key: str) -> _FailingBlob:
        return _FailingBlob(self._message)


class _Client:
    project = "researchflow-ai-491709"


def _build_storage(message: str) -> GCSObjectStorage:
    storage = GCSObjectStorage.__new__(GCSObjectStorage)
    storage._bucket = _Bucket("researchflow_storage", message)
    storage._client = _Client()
    return storage


def _with_source_file(assertions):
    temp_root = Path(__file__).resolve().parents[1] / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="gcp-persistence-test-",
        dir=temp_root,
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write("{}")
        source_path = Path(handle.name)

    try:
        assertions(source_path)
    finally:
        source_path.unlink(missing_ok=True)


def test_upload_file_surfaces_billing_disabled_storage_failures():
    def assertions(source_path: Path):
        storage = _build_storage(
            "403 POST https://storage.googleapis.com/upload/storage/v1/b/researchflow_storage/o "
            "The billing account for the owning project is disabled in state absent"
        )

        with pytest.raises(PersistenceError) as exc_info:
            storage.upload_file(
                "projects/project-123/jobs/job-123/sources/extracted_text.json",
                source_path,
                content_type="application/json",
            )

        message = str(exc_info.value)
        assert "researchflow_storage" in message
        assert "billing disabled" in message.lower()
        assert "active billed project" in message

    _with_source_file(assertions)


def test_upload_file_surfaces_permission_denied_storage_failures():
    def assertions(source_path: Path):
        storage = _build_storage("403 Forbidden")

        with pytest.raises(PersistenceError) as exc_info:
            storage.upload_file(
                "projects/project-123/jobs/job-123/sources/extracted_text.json",
                source_path,
                content_type="application/json",
            )

        message = str(exc_info.value)
        assert "403 forbidden" in message.lower()
        assert "bucket iam" in message.lower()

    _with_source_file(assertions)
