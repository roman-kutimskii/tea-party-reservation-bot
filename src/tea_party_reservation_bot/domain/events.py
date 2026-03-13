from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tea_party_reservation_bot.domain.enums import CancelDeadlineSource, EventStatus
from tea_party_reservation_bot.exceptions import DomainError
from tea_party_reservation_bot.time import to_utc


@dataclass(slots=True, frozen=True)
class EventInputBlock:
    tea_name: str
    starts_at_local: datetime
    capacity: int
    cancel_deadline_at_local: datetime
    cancel_deadline_source: CancelDeadlineSource
    description: str | None = None

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            msg = 'Поле "Мест": только целое число больше 0'
            raise DomainError(msg)
        if self.cancel_deadline_at_local > self.starts_at_local:
            msg = 'Поле "Отмена до": должно быть раньше начала события'
            raise DomainError(msg)


@dataclass(slots=True, frozen=True)
class EventDraft:
    tea_name: str
    description: str | None
    starts_at_local: datetime
    starts_at_utc: datetime
    capacity: int
    cancel_deadline_source: CancelDeadlineSource
    cancel_deadline_at_local: datetime
    cancel_deadline_at_utc: datetime
    status: EventStatus = EventStatus.DRAFT

    @classmethod
    def from_input_block(cls, block: EventInputBlock) -> EventDraft:
        return cls(
            tea_name=block.tea_name,
            description=block.description,
            starts_at_local=block.starts_at_local,
            starts_at_utc=to_utc(block.starts_at_local),
            capacity=block.capacity,
            cancel_deadline_source=block.cancel_deadline_source,
            cancel_deadline_at_local=block.cancel_deadline_at_local,
            cancel_deadline_at_utc=to_utc(block.cancel_deadline_at_local),
        )


@dataclass(slots=True, frozen=True)
class EventPreview:
    normalized: EventDraft
    block_number: int
