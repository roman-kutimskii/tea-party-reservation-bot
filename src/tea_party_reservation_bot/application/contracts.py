from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, Self

from tea_party_reservation_bot.application.dto import (
    ActiveRegistrationView,
    AdminRoleAssignmentView,
    NotificationPreferenceView,
    OutboxMessage,
    ProcessedCommandResult,
    PublicationIntent,
    RosterEntryView,
    StoredEvent,
    StoredUser,
    SystemSettingsView,
    TelegramProfile,
)
from tea_party_reservation_bot.domain.enums import AdminRole, Permission
from tea_party_reservation_bot.domain.events import EventDraft
from tea_party_reservation_bot.domain.rbac import Actor


class Clock(Protocol):
    def now(self) -> datetime: ...


class AuthorizationService(Protocol):
    def require(self, actor: Actor, permission: Permission) -> None: ...


class UserRepository(Protocol):
    async def ensure_from_telegram_profile(self, profile: TelegramProfile) -> StoredUser: ...
    async def get_by_telegram_user_id(self, telegram_user_id: int) -> StoredUser | None: ...
    async def get_by_id(self, user_id: int) -> StoredUser | None: ...


class AdminRoleRepository(Protocol):
    async def get_roles_for_telegram_user(self, telegram_user_id: int) -> frozenset[AdminRole]: ...
    async def get_actor(self, telegram_user_id: int) -> Actor: ...
    async def list_admin_role_assignments(self) -> list[AdminRoleAssignmentView]: ...
    async def assign_role(self, *, user_id: int, role: AdminRole) -> bool: ...
    async def revoke_role(self, *, user_id: int, role: AdminRole) -> bool: ...
    async def count_users_with_role(self, role: AdminRole) -> int: ...


class SystemSettingsRepository(Protocol):
    async def get(self) -> SystemSettingsView: ...
    async def set_default_cancel_deadline_offset_minutes(
        self, minutes: int
    ) -> SystemSettingsView: ...


class EventDraftRepository(Protocol):
    async def save_drafts(
        self, drafts: Sequence[EventDraft], *, actor_user_id: int, timezone_name: str
    ) -> list[int]: ...


class EventRepository(Protocol):
    async def get_by_id(self, event_id: int, *, for_update: bool = False) -> Any: ...
    async def list_published_upcoming(self, now: datetime) -> list[StoredEvent]: ...
    async def list_publication_event_ids(self, batch_id: int) -> tuple[int, ...]: ...
    async def list_active_registrations_for_user(
        self, user_id: int
    ) -> list[ActiveRegistrationView]: ...
    async def get_roster(self, event_id: int) -> list[RosterEntryView]: ...
    async def list_active_participant_telegram_user_ids(self, event_id: int) -> list[int]: ...
    async def mark_publication_succeeded(
        self,
        *,
        event_ids: Sequence[int],
        chat_id: int,
        message_id: int,
        published_at: datetime,
    ) -> None: ...
    async def mark_publication_failed(self, *, event_ids: Sequence[int]) -> None: ...


class EventStore(EventDraftRepository, EventRepository, Protocol):
    pass


class PublicationRepository(Protocol):
    async def create_single_event_publication_intent(
        self, *, event_id: int, actor_user_id: int
    ) -> PublicationIntent: ...
    async def create_batch_publication_intent(
        self, *, event_ids: Sequence[int], actor_user_id: int, period_label: str | None
    ) -> PublicationIntent: ...
    async def mark_batch_state(
        self,
        *,
        batch_id: int,
        status: str,
        published_at: datetime | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> None: ...


class RegistrationRepository(Protocol):
    async def get_active_reservation(self, *, event_id: int, user_id: int) -> Any: ...
    async def get_active_waitlist_entry(self, *, event_id: int, user_id: int) -> Any: ...
    async def list_active_waitlist_entries(self, *, event_id: int) -> list[Any]: ...
    async def create_confirmed_reservation(
        self,
        *,
        event_id: int,
        user_id: int,
        source: str,
        promoted_from_waitlist_entry_id: int | None = None,
    ) -> Any: ...
    async def create_waitlist_entry(self, *, event_id: int, user_id: int) -> Any: ...
    async def next_waitlist_entry_for_promotion(
        self, *, event_id: int, exclude_user_ids: Sequence[int] = ()
    ) -> Any: ...


class NotificationPreferenceRepository(Protocol):
    async def get_or_create(self, user_id: int) -> NotificationPreferenceView: ...
    async def set_enabled(self, user_id: int, enabled: bool) -> NotificationPreferenceView: ...


class OutboxPort(Protocol):
    async def enqueue(self, message: OutboxMessage) -> None: ...


class IdempotencyRepository(Protocol):
    async def get(self, *, source: str, idempotency_key: str) -> ProcessedCommandResult | None: ...
    async def record(
        self, *, source: str, idempotency_key: str, result_ref: str | None
    ) -> None: ...
    def dump_result(self, payload: dict[str, Any]) -> str: ...
    def load_result(self, payload: str | None) -> dict[str, Any] | None: ...


class AuditLogRepository(Protocol):
    async def append(
        self,
        *,
        actor_user_id: int,
        action: str,
        target_type: str,
        target_id: str,
        payload_json: dict[str, Any],
    ) -> None: ...


class UnitOfWork(Protocol):
    users: UserRepository
    roles: AdminRoleRepository
    settings: SystemSettingsRepository
    events: EventStore
    registrations: RegistrationRepository
    publications: PublicationRepository
    notifications: NotificationPreferenceRepository
    outbox: OutboxPort
    idempotency: IdempotencyRepository
    audit_log: AuditLogRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
