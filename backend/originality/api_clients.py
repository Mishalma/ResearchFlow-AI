from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from originality.config import OriginalityConfig
from originality.schemas import ProviderFinding, ProviderSectionScan
from originality.utils import (
    normalize_whitespace,
    wait_for_callback_payload,
)

logger = logging.getLogger("papereasy.backend.originality.providers")


class ProviderClientError(RuntimeError):
    """Raised when an originality provider request fails."""


class BaseOriginalityClient:
    provider_name = "provider"

    def __init__(self, config: OriginalityConfig, *, callback_base_dir: Path | None = None):
        self.config = config
        self.callback_base_dir = callback_base_dir

    async def _request_json(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response_text = await self._request_text(
            url=url,
            params=params,
            headers={**(headers or {}), "Accept": "application/json"},
            method=method,
            payload=payload,
        )
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ProviderClientError(f"Invalid JSON response from {url}") from exc

    async def _request_text(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> str:
        attempts = max(1, self.config.retry_attempts)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.to_thread(
                    self._request_text_sync,
                    url=url,
                    params=params,
                    headers=headers,
                    method=method,
                    payload=payload,
                )
            except ProviderClientError as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(self.config.retry_backoff_seconds * attempt)
        raise ProviderClientError(str(last_error or f"Request to {url} failed"))

    def _request_text_sync(
        self,
        *,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> str:
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value not in (None, "")},
            doseq=True,
        )
        full_url = f"{url}?{query}" if query else url
        data = None
        request_headers = {"User-Agent": "PaperEasyOriginalityAgent/1.0", **(headers or {})}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(full_url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.config.http_timeout_seconds) as response:
                charset = response.headers.get_content_charset("utf-8")
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderClientError(f"{method} {full_url} failed with status {exc.code}: {detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise ProviderClientError(f"{method} {full_url} failed: {exc.reason}") from exc

    async def scan_text(
        self,
        *,
        section_name: str,
        text: str,
        trace_id: str,
    ) -> ProviderSectionScan:
        raise NotImplementedError


class WinstonAIClient(BaseOriginalityClient):
    provider_name = "winston_ai"

    async def scan_text(
        self,
        *,
        section_name: str,
        text: str,
        trace_id: str,
    ) -> ProviderSectionScan:
        if not self.config.winston_api_key:
            raise ProviderClientError("WINSTON_API_KEY is not configured.")

        payload = {
            "text": text,
            "language": self.config.winston_language,
            "country": self.config.winston_country,
        }
        response = await self._request_json(
            url=f"{self.config.winston_base_url}{self.config.winston_plagiarism_path}",
            method="POST",
            headers={"Authorization": f"Bearer {self.config.winston_api_key}"},
            payload=payload,
        )
        return self._parse_response(section_name=section_name, text=text, payload=response, trace_id=trace_id)

    def _parse_response(
        self,
        *,
        section_name: str,
        text: str,
        payload: dict[str, Any],
        trace_id: str,
    ) -> ProviderSectionScan:
        raw_score = (
            payload.get("score")
            or payload.get("plagiarismScore")
            or (payload.get("result") or {}).get("score")
            or (payload.get("data") or {}).get("score")
        )
        originality_score = _invert_score(raw_score)
        ai_score = _coerce_unit_score(
            payload.get("aiScore")
            or payload.get("ai_score")
            or (payload.get("result") or {}).get("aiScore")
        )

        source_records = (
            payload.get("sources")
            or payload.get("matches")
            or (payload.get("result") or {}).get("sources")
            or (payload.get("data") or {}).get("sources")
            or []
        )
        spans: list[ProviderFinding] = []
        for source in source_records:
            source_title = normalize_whitespace(
                source.get("title")
                or source.get("sourceTitle")
                or source.get("name")
            ) or None
            source_url = str(
                source.get("url")
                or source.get("sourceUrl")
                or source.get("link")
                or ""
            ).strip() or None
            source_score = _coerce_unit_score(
                source.get("score")
                or source.get("similarity")
                or source.get("percentage")
            ) or 0.0
            match_items = (
                source.get("plagiarismFound")
                or source.get("matches")
                or source.get("fragments")
                or []
            )
            if not match_items and source_title:
                match_items = [source]
            for item in match_items:
                start_char = _coerce_int(
                    item.get("start")
                    or item.get("startIndex")
                    or item.get("offset")
                    or item.get("begin")
                )
                end_char = _coerce_int(item.get("end") or item.get("endIndex"))
                length = _coerce_int(item.get("length") or item.get("charCount"))
                if end_char is None and start_char is not None and length is not None:
                    end_char = min(len(text), start_char + length)
                if start_char is None:
                    snippet = normalize_whitespace(item.get("sequence") or item.get("text") or "")
                    start_char = text.find(snippet) if snippet else -1
                    if start_char >= 0:
                        end_char = start_char + len(snippet)
                if start_char is None or start_char < 0:
                    continue
                if end_char is None or end_char < start_char:
                    end_char = min(len(text), start_char + len(normalize_whitespace(item.get("sequence") or item.get("text") or "")))
                if end_char <= start_char:
                    continue
                matched_text = normalize_whitespace(
                    item.get("sequence") or item.get("text") or text[start_char:end_char]
                )
                spans.append(
                    ProviderFinding(
                        start_char=start_char,
                        end_char=min(len(text), end_char),
                        matched_text=matched_text or text[start_char:end_char],
                        similarity_score=source_score,
                        matched_source_title=source_title,
                        matched_source_url=source_url,
                        severity=max(source_score, _coerce_unit_score(item.get("score")) or 0.0),
                        metadata={
                            "provider_name": self.provider_name,
                            "trace_id": trace_id,
                            "provider_payload": item,
                        },
                    )
                )

        return ProviderSectionScan(
            provider_name=self.provider_name,
            section_name=section_name,
            originality_score=originality_score if originality_score is not None else _derive_originality_from_spans(spans),
            ai_score=ai_score,
            spans=sorted(spans, key=lambda span: (span.start_char, span.end_char)),
            raw_payload=payload,
            metadata={"trace_id": trace_id},
        )


class CopyleaksClient(BaseOriginalityClient):
    provider_name = "copyleaks"

    def __init__(self, config: OriginalityConfig, *, callback_base_dir: Path | None = None):
        super().__init__(config, callback_base_dir=callback_base_dir)
        self._token: str | None = None
        self._token_timestamp = 0.0

    async def scan_text(
        self,
        *,
        section_name: str,
        text: str,
        trace_id: str,
    ) -> ProviderSectionScan:
        if not self.config.copyleaks_email or not self.config.copyleaks_api_key:
            raise ProviderClientError("Copyleaks credentials are not configured.")
        if not self.config.copyleaks_callback_base_url:
            raise ProviderClientError("COPYLEAKS_CALLBACK_BASE_URL is required for Copyleaks fallback scans.")
        if self.callback_base_dir is None:
            raise ProviderClientError("A callback persistence directory is required for Copyleaks fallback scans.")

        token = await self._authenticate()
        scan_id = f"papereasy-{uuid4()}"
        status_template = (
            f"{self.config.copyleaks_callback_base_url.rstrip('/')}"
            f"/webhooks/originality/copyleaks/status/{scan_id}" + "/{STATUS}"
        )
        export_completed_url = (
            f"{self.config.copyleaks_callback_base_url.rstrip('/')}"
            f"/webhooks/originality/copyleaks/export/{scan_id}/completed"
        )
        text_bytes = text.encode("utf-8")
        submit_payload = {
            "base64": base64.b64encode(text_bytes).decode("ascii"),
            "filename": f"{section_name}.txt",
            "properties": {
                "sandbox": self.config.copyleaks_sandbox,
                "statusWebhook": status_template,
                "webhooks": {
                    "status": status_template,
                },
            },
        }
        await self._request_text(
            url=f"{self.config.copyleaks_api_base_url}/v3/scans/submit/file/{scan_id}",
            method="PUT",
            headers={"Authorization": f"Bearer {token}"},
            payload=submit_payload,
        )

        completed_payload = await wait_for_callback_payload(
            base_dir=self.callback_base_dir,
            scan_id=scan_id,
            event_name="status-completed",
            timeout_seconds=self.config.copyleaks_wait_timeout_seconds,
            poll_interval_seconds=self.config.copyleaks_poll_interval_seconds,
        )
        if completed_payload is None:
            raise ProviderClientError("Timed out waiting for Copyleaks completion webhook.")

        result_descriptors = _collect_copyleaks_results(completed_payload)
        if not result_descriptors:
            return ProviderSectionScan(
                provider_name=self.provider_name,
                section_name=section_name,
                originality_score=_invert_score(
                    (completed_payload.get("results") or {}).get("score")
                    or completed_payload.get("aggregatedScore")
                ) or 1.0,
                spans=[],
                raw_payload=completed_payload,
                metadata={"trace_id": trace_id, "scan_id": scan_id},
            )

        export_id = str(uuid4())
        export_payload = {
            "completionWebhook": export_completed_url,
            "results": [
                {
                    "id": descriptor["id"],
                    "endpoint": (
                        f"{self.config.copyleaks_callback_base_url.rstrip('/')}"
                        f"/webhooks/originality/copyleaks/export/{scan_id}/result/{descriptor['id']}"
                    ),
                    "verb": "POST",
                }
                for descriptor in result_descriptors
            ],
        }
        await self._request_text(
            url=f"{self.config.copyleaks_api_base_url}/v3/downloads/{scan_id}/export/{export_id}",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            payload=export_payload,
        )

        export_completed = await wait_for_callback_payload(
            base_dir=self.callback_base_dir,
            scan_id=scan_id,
            event_name="export-completed",
            timeout_seconds=self.config.copyleaks_wait_timeout_seconds,
            poll_interval_seconds=self.config.copyleaks_poll_interval_seconds,
        )
        if export_completed is None:
            raise ProviderClientError("Timed out waiting for Copyleaks export completion webhook.")

        spans: list[ProviderFinding] = []
        for descriptor in result_descriptors:
            payload = await wait_for_callback_payload(
                base_dir=self.callback_base_dir,
                scan_id=scan_id,
                event_name=f"result-{descriptor['id']}",
                timeout_seconds=self.config.copyleaks_wait_timeout_seconds,
                poll_interval_seconds=self.config.copyleaks_poll_interval_seconds,
            )
            if payload is None:
                continue
            spans.extend(
                _parse_copyleaks_result_payload(
                    section_text=text,
                    payload=payload,
                    descriptor=descriptor,
                    trace_id=trace_id,
                )
            )

        originality_score = _invert_score(
            (completed_payload.get("results") or {}).get("score")
            or completed_payload.get("aggregatedScore")
            or completed_payload.get("score")
        )
        return ProviderSectionScan(
            provider_name=self.provider_name,
            section_name=section_name,
            originality_score=originality_score if originality_score is not None else _derive_originality_from_spans(spans),
            spans=sorted(spans, key=lambda span: (span.start_char, span.end_char)),
            raw_payload={
                "completed": completed_payload,
                "export_completed": export_completed,
            },
            metadata={"trace_id": trace_id, "scan_id": scan_id},
        )

    async def _authenticate(self) -> str:
        if self._token and (time.time() - self._token_timestamp) < 3000:
            return self._token
        response_text = await self._request_text(
            url=f"{self.config.copyleaks_id_base_url}/v3/account/login/api",
            method="POST",
            payload={
                "email": self.config.copyleaks_email,
                "key": self.config.copyleaks_api_key,
            },
            headers={"Accept": "application/json"},
        )
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            token = response_text.strip().strip('"')
        else:
            token = str(
                payload.get("access_token")
                or payload.get("accessToken")
                or payload.get("token")
                or ""
            ).strip()
        if not token:
            raise ProviderClientError("Copyleaks authentication did not return an access token.")
        self._token = token
        self._token_timestamp = time.time()
        return token


def _collect_copyleaks_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results_root = payload.get("results") or {}
    descriptors: list[dict[str, Any]] = []
    for bucket_name, bucket in results_root.items():
        if bucket_name == "score":
            continue
        if isinstance(bucket, list):
            for item in bucket:
                result_id = str(item.get("id") or item.get("resultId") or "").strip()
                if not result_id:
                    continue
                descriptors.append(
                    {
                        "id": result_id,
                        "title": normalize_whitespace(item.get("title") or item.get("name")),
                        "url": str(item.get("url") or item.get("sourceUrl") or "").strip() or None,
                        "bucket": bucket_name,
                        "raw": item,
                    }
                )
    return descriptors


def _parse_copyleaks_result_payload(
    *,
    section_text: str,
    payload: dict[str, Any],
    descriptor: dict[str, Any],
    trace_id: str,
) -> list[ProviderFinding]:
    text_root = payload.get("text") or {}
    comparison_root = text_root.get("comparison") or payload.get("comparison") or {}
    candidate_ranges: list[tuple[int, int, float]] = []
    for category_name, category_weight in (
        ("identical", 0.98),
        ("minorChanges", 0.78),
        ("relatedMeaning", 0.62),
    ):
        category = comparison_root.get(category_name) or {}
        starts = category.get("starts") or []
        lengths = category.get("lengths") or []
        suspected = category.get("suspected") or {}
        if suspected:
            starts = suspected.get("starts") or starts
            lengths = suspected.get("lengths") or lengths
        for start, length in zip(starts, lengths):
            try:
                start_char = int(start)
                span_length = int(length)
            except (TypeError, ValueError):
                continue
            if span_length <= 0:
                continue
            candidate_ranges.append((start_char, min(len(section_text), start_char + span_length), category_weight))

    if not candidate_ranges and payload.get("matchedText"):
        snippet = normalize_whitespace(payload.get("matchedText"))
        if snippet:
            start_char = section_text.find(snippet)
            if start_char >= 0:
                candidate_ranges.append((start_char, start_char + len(snippet), 0.8))

    findings: list[ProviderFinding] = []
    for start_char, end_char, weight in candidate_ranges:
        if end_char <= start_char:
            continue
        findings.append(
            ProviderFinding(
                start_char=start_char,
                end_char=end_char,
                matched_text=section_text[start_char:end_char],
                similarity_score=_coerce_unit_score(
                    payload.get("score")
                    or payload.get("similarity")
                    or descriptor.get("raw", {}).get("score")
                ),
                matched_source_title=descriptor.get("title"),
                matched_source_url=descriptor.get("url"),
                severity=max(
                    weight,
                    _coerce_unit_score(payload.get("score") or descriptor.get("raw", {}).get("score")) or 0.0,
                ),
                metadata={
                    "provider_name": "copyleaks",
                    "trace_id": trace_id,
                    "provider_payload": payload,
                    "bucket": descriptor.get("bucket"),
                },
            )
        )
    return findings


def _coerce_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_unit_score(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1.0:
        score = score / 100.0
    return round(min(1.0, max(0.0, score)), 4)


def _invert_score(value: object) -> float | None:
    score = _coerce_unit_score(value)
    if score is None:
        return None
    return round(min(1.0, max(0.0, 1.0 - score)), 4)


def _derive_originality_from_spans(spans: list[ProviderFinding]) -> float:
    if not spans:
        return 1.0
    return round(max(0.0, 1.0 - max(span.severity for span in spans)), 4)
