from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from tea_party_reservation_bot.application.contracts import (
    AdminRoleRepository,
    AuthorizationService,
)
from tea_party_reservation_bot.domain.enums import Permission
from tea_party_reservation_bot.domain.events import EventPreview
from tea_party_reservation_bot.domain.rbac import Actor, RoleSet

if TYPE_CHECKING:
    from tea_party_reservation_bot.application.services import EventDraftingService
else:
    EventDraftingService = Any


@dataclass(slots=True, frozen=True)
class TelegramUserProfile:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None


@dataclass(slots=True, frozen=True)
class PublicEventView:
    event_id: str
    tea_name: str
    starts_at_local: datetime
    cancel_deadline_at_local: datetime
    capacity: int
    reserved_seats: int
    description: str | None = None
    status: str = "published_open"
    registration_open: bool = True

    @property
    def seats_left(self) -> int:
        return max(self.capacity - self.reserved_seats, 0)

    @property
    def is_full(self) -> bool:
        return self.seats_left == 0


@dataclass(slots=True, frozen=True)
class UserRegistrationView:
    registration_id: str
    event_id: str
    tea_name: str
    starts_at_local: datetime
    cancel_deadline_at_local: datetime
    status: str
    can_cancel: bool
    waitlist_position: int | None = None


@dataclass(slots=True, frozen=True)
class RegistrationResult:
    event: PublicEventView
    status: str


@dataclass(slots=True, frozen=True)
class NotificationSettingsView:
    enabled: bool


@dataclass(slots=True, frozen=True)
class AdminEventView:
    event_id: str
    tea_name: str
    starts_at_local: datetime
    capacity: int
    reserved_seats: int
    status: str


@dataclass(slots=True, frozen=True)
class ParticipantView:
    display_name: str
    status: str
    joined_at_local: datetime | None = None


@dataclass(slots=True, frozen=True)
class EventRosterView:
    event: AdminEventView
    participants: Sequence[ParticipantView]
    waitlist: Sequence[ParticipantView]


@dataclass(slots=True, frozen=True)
class PublicationReceipt:
    accepted: bool
    message: str


class TelegramUserSyncPort(Protocol):
    async def upsert_user(self, profile: TelegramUserProfile) -> None: ...


class EventReadModelPort(Protocol):
    async def list_public_events(self) -> Sequence[PublicEventView]: ...

    async def get_public_event(self, event_id: str) -> PublicEventView | None: ...

    async def list_admin_events(self) -> Sequence[AdminEventView]: ...

    async def get_event_roster(self, event_id: str) -> EventRosterView | None: ...


class RegistrationCommandPort(Protocol):
    async def register_for_event(
        self,
        *,
        telegram_user_id: int,
        event_id: str,
        idempotency_key: str,
    ) -> RegistrationResult: ...

    async def list_user_registrations(
        self,
        *,
        telegram_user_id: int,
    ) -> Sequence[UserRegistrationView]: ...

    async def cancel_registration(
        self,
        *,
        telegram_user_id: int,
        registration_id: str,
        idempotency_key: str,
    ) -> bool: ...


class NotificationPreferencePort(Protocol):
    async def get_settings(self, *, telegram_user_id: int) -> NotificationSettingsView: ...

    async def set_enabled(
        self,
        *,
        telegram_user_id: int,
        enabled: bool,
    ) -> NotificationSettingsView: ...


class PublicationWorkflowPort(Protocol):
    async def publish_single(
        self, *, actor: Actor, preview: EventPreview, idempotency_key: str
    ) -> PublicationReceipt: ...

    async def publish_batch(
        self,
        *,
        actor: Actor,
        previews: Sequence[EventPreview],
        idempotency_key: str,
    ) -> PublicationReceipt: ...


@dataclass(slots=True)
class TelegramBotApplicationService:
    roles: AdminRoleRepository
    authorization_service: AuthorizationService
    drafting_service: EventDraftingService
    user_sync: TelegramUserSyncPort
    events: EventReadModelPort
    registrations: RegistrationCommandPort
    notifications: NotificationPreferencePort
    publication: PublicationWorkflowPort

    async def sync_profile(self, profile: TelegramUserProfile) -> Actor:
        await self.user_sync.upsert_user(profile)
        roles = await self.roles.get_roles_for_telegram_user(profile.telegram_user_id)
        return Actor(telegram_user_id=profile.telegram_user_id, roles=RoleSet(roles))

    async def list_events(self) -> Sequence[PublicEventView]:
        return await self.events.list_public_events()

    async def get_event(self, event_id: str) -> PublicEventView | None:
        return await self.events.get_public_event(event_id)

    async def register_for_event(
        self,
        *,
        telegram_user_id: int,
        event_id: str,
        idempotency_key: str,
    ) -> RegistrationResult:
        return await self.registrations.register_for_event(
            telegram_user_id=telegram_user_id,
            event_id=event_id,
            idempotency_key=idempotency_key,
        )

    async def list_my_registrations(
        self,
        *,
        telegram_user_id: int,
    ) -> Sequence[UserRegistrationView]:
        return await self.registrations.list_user_registrations(telegram_user_id=telegram_user_id)

    async def cancel_registration(
        self,
        *,
        telegram_user_id: int,
        registration_id: str,
        idempotency_key: str,
    ) -> bool:
        return await self.registrations.cancel_registration(
            telegram_user_id=telegram_user_id,
            registration_id=registration_id,
            idempotency_key=idempotency_key,
        )

    async def get_notifications(self, *, telegram_user_id: int) -> NotificationSettingsView:
        return await self.notifications.get_settings(telegram_user_id=telegram_user_id)

    async def toggle_notifications(self, *, telegram_user_id: int) -> NotificationSettingsView:
        current = await self.notifications.get_settings(telegram_user_id=telegram_user_id)
        return await self.notifications.set_enabled(
            telegram_user_id=telegram_user_id,
            enabled=not current.enabled,
        )

    async def list_admin_events(self, actor: Actor) -> Sequence[AdminEventView]:
        self.authorization_service.require(actor, Permission.VIEW_EVENTS)
        return await self.events.list_admin_events()

    async def get_event_roster(self, *, actor: Actor, event_id: str) -> EventRosterView | None:
        self.authorization_service.require(actor, Permission.MANAGE_REGISTRATIONS)
        return await self.events.get_event_roster(event_id)

    def preview_single_event(self, actor: Actor, raw_text: str) -> EventPreview:
        return self.drafting_service.preview_from_text(actor, raw_text)[0]

    def preview_batch(self, actor: Actor, raw_text: str) -> Sequence[EventPreview]:
        return self.drafting_service.preview_from_text(actor, raw_text)

    def ensure_admin(self, actor: Actor) -> None:
        self.authorization_service.require(actor, Permission.VIEW_EVENTS)

    async def publish_single_event(
        self, *, actor: Actor, raw_text: str, idempotency_key: str
    ) -> PublicationReceipt:
        preview = self.preview_single_event(actor, raw_text)
        return await self.publication.publish_single(
            actor=actor,
            preview=preview,
            idempotency_key=idempotency_key,
        )

    async def publish_batch_events(
        self, *, actor: Actor, raw_text: str, idempotency_key: str
    ) -> PublicationReceipt:
        previews = self.preview_batch(actor, raw_text)
        return await self.publication.publish_batch(
            actor=actor,
            previews=previews,
            idempotency_key=idempotency_key,
        )
