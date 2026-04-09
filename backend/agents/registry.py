from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from core.config import Settings, get_settings
from core.exceptions import GenerationConfigurationError
from models.agent_runtime import AgentRegistryConfig, AgentSpec


class AgentRegistry:
    def __init__(self, specs: list[AgentSpec]):
        self._specs = {spec.name: spec for spec in specs}

    def get(self, agent_name: str) -> AgentSpec:
        spec = self._specs.get(agent_name)
        if spec is None:
            raise GenerationConfigurationError(
                f"Agent specification for '{agent_name}' is not configured."
            )
        return spec

    def all(self) -> list[AgentSpec]:
        return list(self._specs.values())


def _load_registry_config(path: Path) -> AgentRegistryConfig:
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GenerationConfigurationError(
            f"Agent configuration file '{path}' was not found."
        ) from exc
    except json.JSONDecodeError as exc:
        raise GenerationConfigurationError(
            f"Agent configuration file '{path}' contains invalid JSON."
        ) from exc

    return AgentRegistryConfig.model_validate(raw_data)


@lru_cache(maxsize=4)
def _build_registry(settings: Settings) -> AgentRegistry:
    config = _load_registry_config(settings.agent_specs_path)
    specs: list[AgentSpec] = []
    for spec in config.agents:
        specs.append(
            spec.model_copy(
                update={
                    "model": spec.model or settings.vertex_model,
                }
            )
        )

    return AgentRegistry(specs)


def get_agent_registry(settings: Settings | None = None) -> AgentRegistry:
    resolved_settings = settings or get_settings()
    return _build_registry(resolved_settings)
