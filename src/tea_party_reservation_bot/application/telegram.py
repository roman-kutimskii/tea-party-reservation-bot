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
    from tea_party_reservation_bot.application.services import (
        AdminAuditService,
        EventDraftingService,
    )
else:
    AdminAuditService = Any
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
    cancel_deadline_at_local: datetime
    cancel_deadline_passed: bool
    capacity: int
    reserved_seats: int
    status: str


@dataclass(slots=True, frozen=True)
class ParticipantView:
    display_name: str
    telegram_user_id: int
    status: str
    joined_at_local: datetime | None = None


@dataclass(slots=True, frozen=True)
class EventRosterView:
    event: AdminEventView
    participants: Sequence[ParticipantView]
    waitlist: Sequence[ParticipantView]


@dataclass(slots=True, frozen=True)
class AdminRoleAssignmentView:
    telegram_user_id: int
    display_name: str
    roles: Sequence[str]


@dataclass(slots=True, frozen=True)
class ManagedSystemSettingsView:
    default_cancel_deadline_offset_minutes: int


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


class AdminEventCommandPort(Protocol):
    async def set_event_name(self, *, actor: Actor, event_id: str, tea_name: str) -> str: ...

    async def set_event_description(
        self, *, actor: Actor, event_id: str, description: str | None
    ) -> str: ...

    async def set_event_start(self, *, actor: Actor, event_id: str, starts_at: str) -> str: ...

    async def set_event_cancel_deadline(
        self, *, actor: Actor, event_id: str, cancel_deadline_at: str
    ) -> str: ...

    async def set_event_capacity(self, *, actor: Actor, event_id: str, capacity: str) -> str: ...

    async def close_registration(self, *, actor: Actor, event_id: str) -> str: ...

    async def reopen_registration(self, *, actor: Actor, event_id: str) -> str: ...

    async def cancel_event(self, *, actor: Actor, event_id: str) -> str: ...

    async def add_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, target: str
    ) -> str: ...

    async def remove_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str
    ) -> str: ...

    async def override_participant_cancellation(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, idempotency_key: str
    ) -> str: ...

    async def move_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, target: str
    ) -> str: ...


class AdminRoleManagementPort(Protocol):
    async def list_assignments(self, *, actor: Actor) -> Sequence[AdminRoleAssignmentView]: ...

    async def assign_role(self, *, actor: Actor, telegram_user_id: str, role: str) -> str: ...

    async def revoke_role(self, *, actor: Actor, telegram_user_id: str, role: str) -> str: ...


class SystemSettingsManagementPort(Protocol):
    async def get_settings(self, *, actor: Actor) -> ManagedSystemSettingsView: ...

    async def set_default_cancel_deadline_offset_minutes(
        self, *, actor: Actor, minutes: str
    ) -> ManagedSystemSettingsView: ...


@dataclass(slots=True)
class TelegramBotApplicationService:
    roles: AdminRoleRepository
    authorization_service: AuthorizationService
    drafting_service: EventDraftingService
    admin_audit: AdminAuditService
    user_sync: TelegramUserSyncPort
    events: EventReadModelPort
    registrations: RegistrationCommandPort
    notifications: NotificationPreferencePort
    publication: PublicationWorkflowPort
    admin_commands: AdminEventCommandPort
    admin_role_management: AdminRoleManagementPort
    system_settings_management: SystemSettingsManagementPort

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
        events = await self.events.list_admin_events()
        await self.admin_audit.record(
            actor=actor,
            action="admin_events_listed",
            target_type="event_occurrence",
            target_id="*",
            payload_json={"event_count": len(events)},
        )
        return events

    async def get_event_roster(self, *, actor: Actor, event_id: str) -> EventRosterView | None:
        self.authorization_service.require(actor, Permission.MANAGE_REGISTRATIONS)
        roster = await self.events.get_event_roster(event_id)
        await self.admin_audit.record(
            actor=actor,
            action="event_roster_viewed",
            target_type="event_occurrence",
            target_id=event_id,
            payload_json={
                "found": roster is not None,
                "confirmed_count": len(roster.participants) if roster is not None else 0,
                "waitlist_count": len(roster.waitlist) if roster is not None else 0,
            },
        )
        return roster

    async def preview_single_event(self, actor: Actor, raw_text: str) -> EventPreview:
        return (await self.drafting_service.preview_from_text(actor, raw_text))[0]

    async def preview_batch(self, actor: Actor, raw_text: str) -> Sequence[EventPreview]:
        return await self.drafting_service.preview_from_text(actor, raw_text)

    def ensure_admin(self, actor: Actor) -> None:
        self.authorization_service.require(actor, Permission.VIEW_EVENTS)

    async def publish_single_event(
        self, *, actor: Actor, raw_text: str, idempotency_key: str
    ) -> PublicationReceipt:
        preview = await self.preview_single_event(actor, raw_text)
        return await self.publication.publish_single(
            actor=actor,
            preview=preview,
            idempotency_key=idempotency_key,
        )

    async def publish_batch_events(
        self, *, actor: Actor, raw_text: str, idempotency_key: str
    ) -> PublicationReceipt:
        previews = await self.preview_batch(actor, raw_text)
        return await self.publication.publish_batch(
            actor=actor,
            previews=previews,
            idempotency_key=idempotency_key,
        )

    async def set_event_name(self, *, actor: Actor, event_id: str, tea_name: str) -> str:
        return await self.admin_commands.set_event_name(
            actor=actor, event_id=event_id, tea_name=tea_name
        )

    async def set_event_description(
        self, *, actor: Actor, event_id: str, description: str | None
    ) -> str:
        return await self.admin_commands.set_event_description(
            actor=actor,
            event_id=event_id,
            description=description,
        )

    async def set_event_start(self, *, actor: Actor, event_id: str, starts_at: str) -> str:
        return await self.admin_commands.set_event_start(
            actor=actor, event_id=event_id, starts_at=starts_at
        )

    async def set_event_cancel_deadline(
        self, *, actor: Actor, event_id: str, cancel_deadline_at: str
    ) -> str:
        return await self.admin_commands.set_event_cancel_deadline(
            actor=actor,
            event_id=event_id,
            cancel_deadline_at=cancel_deadline_at,
        )

    async def set_event_capacity(self, *, actor: Actor, event_id: str, capacity: str) -> str:
        return await self.admin_commands.set_event_capacity(
            actor=actor,
            event_id=event_id,
            capacity=capacity,
        )

    async def close_event_registration(self, *, actor: Actor, event_id: str) -> str:
        return await self.admin_commands.close_registration(actor=actor, event_id=event_id)

    async def reopen_event_registration(self, *, actor: Actor, event_id: str) -> str:
        return await self.admin_commands.reopen_registration(actor=actor, event_id=event_id)

    async def cancel_admin_event(self, *, actor: Actor, event_id: str) -> str:
        return await self.admin_commands.cancel_event(actor=actor, event_id=event_id)

    async def add_event_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, target: str
    ) -> str:
        return await self.admin_commands.add_participant(
            actor=actor,
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            target=target,
        )

    async def remove_event_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str
    ) -> str:
        return await self.admin_commands.remove_participant(
            actor=actor,
            event_id=event_id,
            telegram_user_id=telegram_user_id,
        )

    async def override_event_registration_cancellation(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, idempotency_key: str
    ) -> str:
        return await self.admin_commands.override_participant_cancellation(
            actor=actor,
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            idempotency_key=idempotency_key,
        )

    async def move_event_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, target: str
    ) -> str:
        return await self.admin_commands.move_participant(
            actor=actor,
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            target=target,
        )

    async def list_admin_role_assignments(
        self, *, actor: Actor
    ) -> Sequence[AdminRoleAssignmentView]:
        return await self.admin_role_management.list_assignments(actor=actor)

    async def assign_admin_role(self, *, actor: Actor, telegram_user_id: str, role: str) -> str:
        return await self.admin_role_management.assign_role(
            actor=actor,
            telegram_user_id=telegram_user_id,
            role=role,
        )

    async def revoke_admin_role(self, *, actor: Actor, telegram_user_id: str, role: str) -> str:
        return await self.admin_role_management.revoke_role(
            actor=actor,
            telegram_user_id=telegram_user_id,
            role=role,
        )

    async def get_system_settings(self, *, actor: Actor) -> ManagedSystemSettingsView:
        return await self.system_settings_management.get_settings(actor=actor)

    async def set_default_cancel_deadline_offset_minutes(
        self, *, actor: Actor, minutes: str
    ) -> ManagedSystemSettingsView:
        return await self.system_settings_management.set_default_cancel_deadline_offset_minutes(
            actor=actor,
            minutes=minutes,
        )
