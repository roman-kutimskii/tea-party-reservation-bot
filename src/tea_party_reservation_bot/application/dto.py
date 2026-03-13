from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class OutboxMessage:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    available_at: datetime
    id: int | None = None
    attempt_count: int = 0
    last_error: str | None = None


@dataclass(slots=True, frozen=True)
class TelegramProfile:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None


@dataclass(slots=True, frozen=True)
class StoredUser:
    id: int
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None


@dataclass(slots=True, frozen=True)
class StoredEvent:
    id: int
    tea_name: str
    description: str | None
    starts_at: datetime
    timezone: str
    capacity: int
    reserved_seats: int
    cancel_deadline_at: datetime
    cancel_deadline_source: str
    status: str
    published_at: datetime | None
    telegram_group_chat_id: int | None
    telegram_group_message_id: int | None


@dataclass(slots=True, frozen=True)
class ActiveRegistrationView:
    reservation_id: int
    event_id: int
    tea_name: str
    starts_at: datetime
    cancel_deadline_at: datetime
    status: str
    waitlist_position: int | None = None


@dataclass(slots=True, frozen=True)
class RosterEntryView:
    user_id: int
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    kind: str
    status: str
    position: int | None
    reservation_id: int | None
    waitlist_entry_id: int | None


@dataclass(slots=True, frozen=True)
class NotificationPreferenceView:
    user_id: int
    new_events_enabled: bool


@dataclass(slots=True, frozen=True)
class ProcessedCommandResult:
    source: str
    idempotency_key: str
    result_ref: str | None


@dataclass(slots=True, frozen=True)
class PublicationIntent:
    batch_id: int | None
    event_ids: tuple[int, ...]
