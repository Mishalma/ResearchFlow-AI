from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class A2AMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    protocol: str = "a2a"
    sender: str
    recipient: str
    task: str
    trace_id: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class A2AResult(BaseModel):
    message: A2AMessage
    success: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(ge=0)
    error: str | None = None
    tools_used: list[str] = Field(default_factory=list)
