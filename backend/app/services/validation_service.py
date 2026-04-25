from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Protocol

import httpx

from core.config import Settings, get_settings
from core.exceptions import ValidationError, WorkflowConfigurationError
from models.validation import ValidationServiceRequest, ValidationServiceResponse
from validation.runtime import execute_validation


class ValidationServiceClient(Protocol):
    async def run_validation(
        self,
        request: ValidationServiceRequest,
    ) -> ValidationServiceResponse: ...


async def execute_validation_request(
    request: ValidationServiceRequest,
    *,
    settings: Settings | None = None,
) -> ValidationServiceResponse:
    resolved_settings = settings or get_settings()
    return await execute_validation(request, settings=resolved_settings)


class LocalValidationServiceClient:
    def __init__(self, *, settings: Settings | None = None):
        self._settings = settings

    async def run_validation(
        self,
        request: ValidationServiceRequest,
    ) -> ValidationServiceResponse:
        return await execute_validation_request(request, settings=self._settings)


async def _default_auth_token_provider(audience: str) -> str | None:
    if not audience:
        return None

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token
    except ImportError as exc:  # pragma: no cover - env dependent
        raise WorkflowConfigurationError(
            "google-auth is required when WORKFLOW_VALIDATION_BACKEND=service."
        ) from exc

    def _fetch() -> str:
        return fetch_id_token(Request(), audience)

    return await asyncio.to_thread(_fetch)


class HttpValidationServiceClient:
    def __init__(
        self,
        *,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        auth_token_provider: Callable[[str], Awaitable[str | None]] | None = None,
    ):
        base_url = settings.validation_service_base_url.rstrip("/")
        if not base_url:
            raise WorkflowConfigurationError(
                "VALIDATION_SERVICE_BASE_URL is required when WORKFLOW_VALIDATION_BACKEND=service."
            )

        self._endpoint = f"{base_url}/internal/validation/run"
        self._audience = settings.validation_service_audience or base_url
        self._timeout_seconds = float(settings.validation_service_timeout_seconds)
        self._transport = transport
        self._auth_token_provider = auth_token_provider or _default_auth_token_provider

    async def run_validation(
        self,
        request: ValidationServiceRequest,
    ) -> ValidationServiceResponse:
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
            message = "Validation service request failed."
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
                "Validation service returned an invalid JSON response.",
                details={"status_code": response.status_code},
            ) from exc

        return ValidationServiceResponse.model_validate(payload)


def get_validation_service_client(
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    auth_token_provider: Callable[[str], Awaitable[str | None]] | None = None,
) -> ValidationServiceClient:
    resolved_settings = settings or get_settings()
    if resolved_settings.workflow_validation_backend == "service":
        return HttpValidationServiceClient(
            settings=resolved_settings,
            transport=transport,
            auth_token_provider=auth_token_provider,
        )

    return LocalValidationServiceClient(settings=resolved_settings)
