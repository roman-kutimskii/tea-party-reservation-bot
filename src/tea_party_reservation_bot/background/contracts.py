from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from tea_party_reservation_bot.application.dto import OutboxMessage


class OutboxProcessor(Protocol):
    async def fetch_pending(self, limit: int = 100) -> Sequence[OutboxMessage]: ...
    async def mark_sent(self, message: OutboxMessage) -> None: ...
    async def mark_failed(self, message: OutboxMessage, reason: str) -> None: ...
