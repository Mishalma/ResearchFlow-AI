from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Protocol

import httpx

from core.config import Settings, get_settings
from core.exceptions import ValidationError, WorkflowConfigurationError
from fix.runtime import execute_fix_request
from models.fix import FixServiceRequest, FixServiceResponse


class FixServiceClient(Protocol):
    async def run_fix(
        self,
        request: FixServiceRequest,
    ) -> FixServiceResponse: ...


async def execute_fix_service_request(
    request: FixServiceRequest,
    *,
    settings: Settings | None = None,
) -> FixServiceResponse:
    resolved_settings = settings or get_settings()
    return await execute_fix_request(request, settings=resolved_settings)


class LocalFixServiceClient:
    def __init__(self, *, settings: Settings | None = None):
        self._settings = settings

    async def run_fix(
        self,
        request: FixServiceRequest,
    ) -> FixServiceResponse:
        return await execute_fix_service_request(request, settings=self._settings)


async def _default_auth_token_provider(audience: str) -> str | None:
    if not audience:
        return None

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token
    except ImportError as exc:  # pragma: no cover - env dependent
        raise WorkflowConfigurationError(
            "google-auth is required when WORKFLOW_FIX_BACKEND=service."
        ) from exc

    def _fetch() -> str:
        return fetch_id_token(Request(), audience)

    return await asyncio.to_thread(_fetch)


class HttpFixServiceClient:
    def __init__(
        self,
        *,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        auth_token_provider: Callable[[str], Awaitable[str | None]] | None = None,
    ):
        base_url = settings.fix_service_base_url.rstrip("/")
        if not base_url:
            raise WorkflowConfigurationError(
                "FIX_SERVICE_BASE_URL is required when WORKFLOW_FIX_BACKEND=service."
            )

        self._endpoint = f"{base_url}/internal/fix/run"
        self._audience = settings.fix_service_audience or base_url
        self._timeout_seconds = float(settings.fix_service_timeout_seconds)
        self._transport = transport
        self._auth_token_provider = auth_token_provider or _default_auth_token_provider

    async def run_fix(
        self,
        request: FixServiceRequest,
    ) -> FixServiceResponse:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        token = await self._auth_token_provider(self._audience)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            response = await client.post(
                self._endpoint,
                json=request.model_dump(mode="json"),
                headers=headers,
            )

        if response.is_error:
            message = "Fix service request failed."
            details: dict[str, object] = {"status_code": response.status_code}
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                details["response"] = payload
                if isinstance(payload.get("error"), str) and payload["error"].strip():
                    message = payload["error"].strip()
            else:
                details["response"] = response.text
            raise ValidationError(message, details=details)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValidationError(
                "Fix service returned an invalid JSON response.",
                details={"status_code": response.status_code},
            ) from exc

        return FixServiceResponse.model_validate(payload)


def get_fix_service_client(
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    auth_token_provider: Callable[[str], Awaitable[str | None]] | None = None,
) -> FixServiceClient:
    resolved_settings = settings or get_settings()
    if resolved_settings.workflow_fix_backend == "service":
        return HttpFixServiceClient(
            settings=resolved_settings,
            transport=transport,
            auth_token_provider=auth_token_provider,
        )

    return LocalFixServiceClient(settings=resolved_settings)
