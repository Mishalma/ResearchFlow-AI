from __future__ import annotations

from pydantic import BaseModel, Field


class RetryPolicy(BaseModel):
    attempts: int = Field(default=1, ge=1)
    backoff_seconds: float = Field(default=0.0, ge=0)


class AgentSpec(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    prompt_template: str = Field(default="")
    input_schema: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    model: str | None = None
    enabled_tools: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=60, ge=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)


class AgentRegistryConfig(BaseModel):
    agents: list[AgentSpec] = Field(default_factory=list)
