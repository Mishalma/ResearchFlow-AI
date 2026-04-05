from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any

from agents.base import BaseAgent
from core.config import Settings, get_settings
from core.exceptions import AgentExecutionError, AppError
from models.a2a import A2AMessage, A2AResult

logger = logging.getLogger("papereasy.backend.a2a")


class A2AManager:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_name] = agent

    async def dispatch(
        self,
        *,
        sender: str,
        recipient: str,
        task: str,
        trace_id: str,
        payload: dict[str, Any],
    ) -> A2AResult:
        agent = self._agents.get(recipient)
        if agent is None:
            raise AgentExecutionError(recipient, "Target agent is not registered.")

        message = A2AMessage(
            sender=sender,
            recipient=recipient,
            task=task,
            trace_id=trace_id,
            payload=payload,
        )
        last_error: Exception | None = None

        for attempt in range(1, self.settings.agent_retry_attempts + 1):
            start_time = perf_counter()
            try:
                result_payload = await agent.receive_message(message)
                duration_ms = (perf_counter() - start_time) * 1000
                logger.info(
                    "A2A message %s -> %s succeeded on attempt %s in %.2f ms",
                    sender,
                    recipient,
                    attempt,
                    duration_ms,
                )
                return A2AResult(
                    message=message,
                    success=True,
                    payload=result_payload,
                    duration_ms=duration_ms,
                )
            except AppError:
                duration_ms = (perf_counter() - start_time) * 1000
                logger.exception(
                    "A2A message %s -> %s failed with application error on attempt %s in %.2f ms",
                    sender,
                    recipient,
                    attempt,
                    duration_ms,
                )
                raise
            except Exception as exc:
                last_error = exc
                duration_ms = (perf_counter() - start_time) * 1000
                logger.exception(
                    "A2A message %s -> %s failed on attempt %s in %.2f ms",
                    sender,
                    recipient,
                    attempt,
                    duration_ms,
                )
                if attempt < self.settings.agent_retry_attempts:
                    await asyncio.sleep(self.settings.agent_retry_backoff_seconds)

        raise AgentExecutionError(recipient, str(last_error)) from last_error
