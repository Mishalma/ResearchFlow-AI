from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from models.a2a import A2AMessage


class BaseAgent(ABC):
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.logger = logging.getLogger(f"papereasy.backend.agent.{agent_name}")

    def send_message(
        self,
        *,
        recipient: str,
        task: str,
        trace_id: str,
        payload: dict[str, Any],
    ) -> A2AMessage:
        return A2AMessage(
            sender=self.agent_name,
            recipient=recipient,
            task=task,
            trace_id=trace_id,
            payload=payload,
        )

    async def receive_message(self, message: A2AMessage) -> dict[str, Any]:
        self.logger.info(
            "Agent %s received %s from %s",
            self.agent_name,
            message.task,
            message.sender,
        )
        return await self.process_task(message)

    @abstractmethod
    async def process_task(self, message: A2AMessage) -> dict[str, Any]:
        raise NotImplementedError
