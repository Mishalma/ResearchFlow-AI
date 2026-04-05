from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from core.config import Settings, get_settings
from core.exceptions import GenerationConfigurationError, GenerationError

TModel = TypeVar("TModel", bound=BaseModel)

logger = logging.getLogger("papereasy.backend.vertex")


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

            response = await async_client.models.generate_content(
                model=model_name or self.settings.vertex_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.settings.ai_temperature,
                    max_output_tokens=self.settings.ai_max_output_tokens,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )

            if response.parsed is not None:
                if isinstance(response.parsed, response_schema):
                    return response.parsed
                return response_schema.model_validate(response.parsed)

            raw_text = (response.text or "").strip()
            if not raw_text:
                raise GenerationError("Vertex AI returned an empty response.")

            try:
                parsed_json = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                logger.exception("Vertex AI returned non-JSON output.")
                raise GenerationError("Vertex AI returned invalid JSON output.") from exc

            return response_schema.model_validate(parsed_json)
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
            logger.exception("Vertex AI client request failed.")
            raise GenerationError("Vertex AI request failed.") from exc
        except Exception as exc:
            logger.exception("Vertex AI generation failed.")
            raise GenerationError("Vertex AI request failed.") from exc
        finally:
            if async_client is not None:
                await async_client.aclose()
            if client is not None:
                client.close()
