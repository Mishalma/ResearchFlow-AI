from __future__ import annotations

import asyncio
import logging
from statistics import mean
from typing import Any

from core.config import Settings
from originality.api_clients import (
    CopyleaksClient,
    ProviderClientError,
    WinstonAIClient,
)
from originality.config import OriginalityConfig
from originality.schemas import ProviderFinding, ProviderSectionScan
from originality.utils import chunk_text

logger = logging.getLogger("papereasy.backend.originality.scanner")


async def scan_sections(
    *,
    section_texts: dict[str, str],
    config: OriginalityConfig,
    settings: Settings,
    trace_id: str,
    winston_client: WinstonAIClient | None = None,
    copyleaks_client: CopyleaksClient | None = None,
    logger_: logging.Logger | None = None,
) -> tuple[dict[str, ProviderSectionScan], dict[str, Any]]:
    active_logger = logger_ or logger
    callback_base_dir = settings.temp_dir
    resolved_winston = winston_client or WinstonAIClient(config)
    resolved_copyleaks = copyleaks_client or CopyleaksClient(
        config,
        callback_base_dir=callback_base_dir,
    )

    tasks = [
        _scan_section(
            section_name=section_name,
            section_text=text,
            config=config,
            trace_id=trace_id,
            winston_client=resolved_winston,
            copyleaks_client=resolved_copyleaks,
            active_logger=active_logger,
        )
        for section_name, text in section_texts.items()
    ]
    results = await asyncio.gather(*tasks)
    section_scans = {section_name: scan for section_name, scan, _ in results}
    metadata = {
        "provider_summary": _merge_provider_counts(result_metadata.get("provider_summary", {}) for _, _, result_metadata in results),
        "provider_failures": {
            section_name: result_metadata.get("provider_failures", [])
            for section_name, _, result_metadata in results
            if result_metadata.get("provider_failures")
        },
    }
    return section_scans, metadata


async def _scan_section(
    *,
    section_name: str,
    section_text: str,
    config: OriginalityConfig,
    trace_id: str,
    winston_client: WinstonAIClient,
    copyleaks_client: CopyleaksClient,
    active_logger: logging.Logger,
) -> tuple[str, ProviderSectionScan, dict[str, Any]]:
    if not section_text.strip():
        return (
            section_name,
            ProviderSectionScan(
                provider_name="none",
                section_name=section_name,
                originality_score=1.0,
                spans=[],
                metadata={"provider_summary": {}},
            ),
            {"provider_summary": {}},
        )

    chunks = chunk_text(
        section_text,
        chunk_size=config.section_chunk_chars,
        overlap=config.section_chunk_overlap_chars,
    )
    combined_spans: list[ProviderFinding] = []
    originality_scores: list[float] = []
    ai_scores: list[float] = []
    provider_summary: dict[str, int] = {}
    provider_failures: list[dict[str, str]] = []
    raw_payloads: list[dict[str, Any]] = []

    for chunk_start, _chunk_end, chunk_text_value in chunks:
        chunk_scan, chunk_failures = await _scan_chunk_with_fallback(
            section_name=section_name,
            chunk_text=chunk_text_value,
            trace_id=trace_id,
            config=config,
            winston_client=winston_client,
            copyleaks_client=copyleaks_client,
            active_logger=active_logger,
        )
        provider_failures.extend(chunk_failures)
        if chunk_scan is None:
            continue
        provider_summary[chunk_scan.provider_name] = provider_summary.get(chunk_scan.provider_name, 0) + 1
        if chunk_scan.originality_score is not None:
            originality_scores.append(chunk_scan.originality_score)
        if chunk_scan.ai_score is not None:
            ai_scores.append(chunk_scan.ai_score)
        raw_payloads.append(chunk_scan.raw_payload)
        for span in chunk_scan.spans:
            combined_spans.append(
                span.model_copy(
                    update={
                        "start_char": span.start_char + chunk_start,
                        "end_char": span.end_char + chunk_start,
                        "metadata": {**span.metadata, "provider_name": chunk_scan.provider_name},
                    }
                )
            )

    scan = ProviderSectionScan(
        provider_name=_select_primary_provider(provider_summary),
        section_name=section_name,
        originality_score=round(mean(originality_scores), 4) if originality_scores else None,
        ai_score=round(mean(ai_scores), 4) if ai_scores else None,
        spans=sorted(combined_spans, key=lambda item: (item.start_char, item.end_char)),
        raw_payload={"chunks": raw_payloads},
        metadata={
            "provider_summary": provider_summary,
            "provider_failures": provider_failures,
            "chunk_count": len(chunks),
        },
    )
    return section_name, scan, {"provider_summary": provider_summary, "provider_failures": provider_failures}


async def _scan_chunk_with_fallback(
    *,
    section_name: str,
    chunk_text: str,
    trace_id: str,
    config: OriginalityConfig,
    winston_client: WinstonAIClient,
    copyleaks_client: CopyleaksClient,
    active_logger: logging.Logger,
) -> tuple[ProviderSectionScan | None, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []

    providers = [
        (config.primary_provider, winston_client if config.primary_provider == "winston_ai" else copyleaks_client),
        (config.fallback_provider, copyleaks_client if config.fallback_provider == "copyleaks" else winston_client),
    ]
    seen_providers: set[str] = set()
    for provider_name, provider_client in providers:
        if provider_name in seen_providers:
            continue
        seen_providers.add(provider_name)
        attempts = 1 + max(0, config.provider_failure_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                return (
                    await provider_client.scan_text(
                        section_name=section_name,
                        text=chunk_text,
                        trace_id=trace_id,
                    ),
                    failures,
                )
            except ProviderClientError as exc:
                failure = {
                    "provider": provider_name,
                    "attempt": str(attempt),
                    "message": str(exc),
                }
                failures.append(failure)
                active_logger.warning(
                    "Originality scan failed for provider %s on section %s attempt %s: %s",
                    provider_name,
                    section_name,
                    attempt,
                    exc,
                )
                if attempt < attempts:
                    await asyncio.sleep(config.retry_backoff_seconds * attempt)
        # move to fallback provider
    return None, failures


def _select_primary_provider(provider_summary: dict[str, int]) -> str:
    if not provider_summary:
        return "none"
    return sorted(provider_summary.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _merge_provider_counts(items: Any) -> dict[str, int]:
    merged: dict[str, int] = {}
    for provider_summary in items:
        for provider, count in provider_summary.items():
            merged[provider] = merged.get(provider, 0) + int(count)
    return merged
