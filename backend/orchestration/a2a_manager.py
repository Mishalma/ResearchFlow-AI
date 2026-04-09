from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Protocol

from agents.base import BaseAgent
from core.config import Settings, get_settings
from core.exceptions import AgentExecutionError, AppError
from models.a2a import A2AMessage, A2AResult

logger = logging.getLogger("papereasy.backend.a2a")


class A2ATransport(Protocol):
    async def deliver(self, agent: BaseAgent, message: A2AMessage) -> dict[str, Any]: ...


class InProcessTransport:
    async def deliver(self, agent: BaseAgent, message: A2AMessage) -> dict[str, Any]:
        return await agent.receive_message(message)


class HttpA2ATransport:
    async def deliver(self, agent: BaseAgent, message: A2AMessage) -> dict[str, Any]:
        raise AgentExecutionError(agent.agent_name, "HTTP A2A transport is not implemented yet.")


class A2AManager:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: A2ATransport | None = None,
    ):
        self.settings = settings or get_settings()
        self.transport = transport or InProcessTransport()
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
        retry_policy = agent.spec.retry_policy

        for attempt in range(1, retry_policy.attempts + 1):
            start_time = perf_counter()
            try:
                result_payload = await self.transport.deliver(agent, message)
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
                if attempt < retry_policy.attempts:
                    await asyncio.sleep(retry_policy.backoff_seconds)

        raise AgentExecutionError(recipient, str(last_error)) from last_error
