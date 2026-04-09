from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from core.config import Settings, get_settings
from core.exceptions import GenerationConfigurationError, GenerationError

TModel = TypeVar("TModel", bound=BaseModel)

logger = logging.getLogger("papereasy.backend.vertex")

JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


class VertexGeminiClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _resolve_credentials_path(self) -> Path | None:
        service_account_path = self.settings.vertex_service_account_file
        if service_account_path is not None:
            return service_account_path

        raw_adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if not raw_adc_path:
            return None

        return Path(raw_adc_path).expanduser().resolve()

    def _build_credentials(self):
        credentials_path = self._resolve_credentials_path()
        if credentials_path is None:
            return None

        if not credentials_path.exists():
            raise GenerationConfigurationError(
                "The configured Google service account file was not found. Set VERTEX_SERVICE_ACCOUNT_FILE or GOOGLE_APPLICATION_CREDENTIALS to an existing JSON file."
            )

        try:
            from google.oauth2 import service_account
        except ImportError as exc:
            raise GenerationConfigurationError(
                "Google authentication dependencies are not installed."
            ) from exc

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        return service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=scopes,
        )

    def _validate_settings(self) -> None:
        if not self.settings.google_cloud_project:
            raise GenerationConfigurationError(
                "GOOGLE_CLOUD_PROJECT is required for Vertex AI generation."
            )

    def _extract_json_candidate(self, raw_text: str) -> str:
        stripped = raw_text.strip()
        if not stripped:
            raise GenerationError("Vertex AI returned an empty response.")

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if fenced_match:
            return fenced_match.group(1).strip()

        direct_match = JSON_OBJECT_PATTERN.search(stripped)
        if direct_match:
            return direct_match.group(0).strip()

        return stripped

    def _parse_structured_response(self, response, response_schema: type[TModel]) -> TModel:
        if response.parsed is not None:
            if isinstance(response.parsed, response_schema):
                return response.parsed
            return response_schema.model_validate(response.parsed)

        raw_text = (response.text or "").strip()
        json_candidate = self._extract_json_candidate(raw_text)

        try:
            parsed_json = json.loads(json_candidate)
        except json.JSONDecodeError as exc:
            logger.debug("Vertex AI raw output: %s", raw_text)
            raise GenerationError("Vertex AI returned invalid JSON output.") from exc

        return response_schema.model_validate(parsed_json)

    async def _repair_invalid_json(
        self,
        *,
        async_client,
        types,
        raw_text: str,
        response_schema: type[TModel],
        model_name: str | None,
    ) -> TModel:
        repair_prompt = (
            "You repair malformed JSON produced by a structured generation system.\n"
            "Return only valid JSON that matches the required schema exactly.\n"
            "Do not add markdown fences or commentary.\n"
            "If any required string field is incomplete or missing, fill it with a brief academically worded placeholder so the JSON remains valid.\n\n"
            f"Required JSON schema:\n{json.dumps(response_schema.model_json_schema(), ensure_ascii=True)}\n\n"
            f"Malformed content to repair:\n{raw_text}"
        )

        repair_response = await async_client.models.generate_content(
            model=model_name or self.settings.vertex_model,
            contents=repair_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=self.settings.ai_max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        return self._parse_structured_response(repair_response, response_schema)

    async def _request_structured_response(
        self,
        *,
        async_client,
        types,
        prompt: str,
        response_schema: type[TModel],
        model_name: str | None,
        attempt: int,
        max_attempts: int,
    ) -> TModel:
        retry_suffix = ""
        if attempt > 1:
            retry_suffix = (
                "\n\nIMPORTANT:\n"
                "- Return only valid JSON.\n"
                "- Do not wrap JSON in markdown fences.\n"
                "- Escape all quotes and line breaks correctly.\n"
                "- Ensure the JSON is complete and parseable.\n"
                "- Keep every required field present and non-empty."
            )

        response = await async_client.models.generate_content(
            model=model_name or self.settings.vertex_model,
            contents=f"{prompt}{retry_suffix}",
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=self.settings.ai_max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        try:
            return self._parse_structured_response(response, response_schema)
        except GenerationError as exc:
            logger.warning(
                "Vertex AI returned invalid JSON on attempt %s/%s.",
                attempt,
                max_attempts,
            )

            raw_text = (response.text or "").strip()
            if raw_text:
                try:
                    repaired_result = await self._repair_invalid_json(
                        async_client=async_client,
                        types=types,
                        raw_text=raw_text,
                        response_schema=response_schema,
                        model_name=model_name,
                    )
                    logger.info(
                        "Recovered Vertex structured response via JSON repair on attempt %s/%s.",
                        attempt,
                        max_attempts,
                    )
                    return repaired_result
                except GenerationError:
                    logger.warning(
                        "Vertex JSON repair failed on attempt %s/%s.",
                        attempt,
                        max_attempts,
                    )

            raise exc

    async def generate_json(
        self,
        *,
        prompt: str,
        response_schema: type[TModel],
        model_name: str | None = None,
    ) -> TModel:
        self._validate_settings()

        try:
            import vertexai
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types
        except ImportError as exc:
            raise GenerationConfigurationError(
                "Vertex AI dependencies are not installed. Run pip install -r requirements.txt."
            ) from exc

        credentials = self._build_credentials()
        client = None
        async_client = None

        try:
            vertexai.init(
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
                credentials=credentials,
            )
            client = genai.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
                credentials=credentials,
                http_options=types.HttpOptions(api_version="v1"),
            )
            async_client = client.aio

            max_attempts = max(1, self.settings.agent_retry_attempts)
            last_generation_error: GenerationError | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await self._request_structured_response(
                        async_client=async_client,
                        types=types,
                        prompt=prompt,
                        response_schema=response_schema,
                        model_name=model_name,
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                except GenerationError as exc:
                    last_generation_error = exc
                    if "invalid JSON output" not in str(exc) or attempt >= max_attempts:
                        raise
                    logger.warning(
                        "Retrying Vertex structured generation after invalid JSON (attempt %s/%s).",
                        attempt,
                        max_attempts,
                    )

            if last_generation_error is not None:
                raise last_generation_error
            raise GenerationError("Vertex AI request failed.")
        except GenerationConfigurationError:
            raise
        except genai_errors.ClientError as exc:
            message = str(exc)
            if "PERMISSION_DENIED" in message or "aiplatform.endpoints.predict" in message:
                raise GenerationConfigurationError(
                    "Vertex AI permission denied. Grant the authenticated principal a role with aiplatform.endpoints.predict, such as Vertex AI User, for this project."
                ) from exc
            if "NOT_FOUND" in message:
                raise GenerationConfigurationError(
                    "The configured Vertex model or location was not found. Verify VERTEX_MODEL and GOOGLE_CLOUD_LOCATION."
                ) from exc
            if "default credentials were not found" in message.lower():
                raise GenerationConfigurationError(
                    "Application Default Credentials were not found. Run gcloud auth application-default login locally or use an attached service account in Cloud Run."
                ) from exc
            logger.exception("Vertex AI client request failed.")
            raise GenerationError("Vertex AI request failed.") from exc
        except Exception as exc:
            message = str(exc)
            if "default credentials" in message.lower():
                raise GenerationConfigurationError(
                    "Application Default Credentials were not found. Run gcloud auth application-default login locally or use an attached service account in Cloud Run."
                ) from exc
            logger.exception("Vertex AI generation failed.")
            raise GenerationError("Vertex AI request failed.") from exc
        finally:
            if async_client is not None:
                await async_client.aclose()
            if client is not None:
                client.close()
