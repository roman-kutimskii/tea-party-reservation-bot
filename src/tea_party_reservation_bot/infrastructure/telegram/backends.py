from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.application.contracts import AdminRoleRepository
from tea_party_reservation_bot.application.dto import TelegramProfile
from tea_party_reservation_bot.application.services import (
    AdminEventService,
    AdminRoleManagementService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    SystemSettingsService,
    UserApplicationService,
)
from tea_party_reservation_bot.application.telegram import (
    AdminEventCommandPort,
    AdminEventView,
    AdminRoleAssignmentView,
    AdminRoleManagementPort,
    EventReadModelPort,
    EventRosterView,
    ManagedSystemSettingsView,
    NotificationPreferencePort,
    NotificationSettingsView,
    ParticipantView,
    PublicationReceipt,
    PublicationWorkflowPort,
    PublicEventView,
    RegistrationCommandPort,
    RegistrationResult,
    SystemSettingsManagementPort,
    TelegramUserProfile,
    TelegramUserSyncPort,
    UserRegistrationView,
)
from tea_party_reservation_bot.domain.enums import (
    AdminRole,
    EventStatus,
    ReservationStatus,
    WaitlistStatus,
)
from tea_party_reservation_bot.domain.events import EventPreview
from tea_party_reservation_bot.domain.rbac import Actor, RoleSet
from tea_party_reservation_bot.exceptions import ApplicationError, ConflictError, NotFoundError
from tea_party_reservation_bot.infrastructure.db.models import (
    EventOccurrenceModel,
    ReservationModel,
    UserModel,
    WaitlistEntryModel,
)
from tea_party_reservation_bot.infrastructure.db.repositories import RoleRepository
from tea_party_reservation_bot.time import now_utc


def _parse_event_id(raw_event_id: str) -> int:
    try:
        return int(raw_event_id)
    except ValueError as exc:
        msg = f"Invalid event id: {raw_event_id}"
        raise LookupError(msg) from exc


def _display_name(user: UserModel) -> str:
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or f"id:{user.telegram_user_id}"


def _display_name_from_parts(
    *, telegram_user_id: int, username: str | None, first_name: str | None, last_name: str | None
) -> str:
    if username:
        return f"@{username}"
    full_name = " ".join(part for part in [first_name, last_name] if part)
    return full_name or f"id:{telegram_user_id}"


def _parse_datetime(value: str, timezone: tzinfo) -> datetime:
    try:
        date_part, time_part = value.strip().split(maxsplit=1)
        day, month, year = (int(token) for token in date_part.split("."))
        hour, minute = (int(token) for token in time_part.split(":"))
        parsed = datetime(year, month, day, hour, minute, tzinfo=timezone)
    except ValueError as exc:
        raise ApplicationError("Используйте формат даты DD.MM.YYYY HH:MM.") from exc
    return parsed.astimezone(now_utc().tzinfo)


def _parse_admin_event_id(raw_event_id: str) -> int:
    try:
        return _parse_event_id(raw_event_id)
    except LookupError as exc:
        raise ApplicationError("Некорректный id события.") from exc


def _parse_telegram_user_id(raw_telegram_user_id: str) -> int:
    try:
        return int(raw_telegram_user_id)
    except ValueError as exc:
        raise ApplicationError("Некорректный telegram_user_id.") from exc


def _parse_admin_role(raw_role: str) -> AdminRole:
    try:
        return AdminRole(raw_role.strip().lower())
    except ValueError as exc:
        raise ApplicationError("Роль должна быть owner или manager.") from exc


def _parse_non_negative_int(raw_value: str, field_name: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ApplicationError(f"Некорректное значение для {field_name}.") from exc
    if value < 0:
        raise ApplicationError(f"{field_name} должно быть неотрицательным.")
    return value


@dataclass(slots=True)
class SqlAlchemyTelegramUserSyncPort(TelegramUserSyncPort):
    user_service: UserApplicationService

    async def upsert_user(self, profile: TelegramUserProfile) -> None:
        await self.user_service.ensure_user(
            TelegramProfile(
                telegram_user_id=profile.telegram_user_id,
                username=profile.username,
                first_name=profile.first_name,
                last_name=profile.last_name,
            )
        )


@dataclass(slots=True)
class SqlAlchemyAdminRoleRepository(AdminRoleRepository):
    session_factory: async_sessionmaker[AsyncSession]

    async def get_roles_for_telegram_user(self, telegram_user_id: int) -> frozenset[AdminRole]:
        async with self.session_factory() as session:
            return await RoleRepository(session).get_roles_for_telegram_user(telegram_user_id)

    async def get_actor(self, telegram_user_id: int) -> Actor:
        return Actor(
            telegram_user_id=telegram_user_id,
            roles=RoleSet(await self.get_roles_for_telegram_user(telegram_user_id)),
        )

    async def list_admin_role_assignments(self) -> list[Any]:
        async with self.session_factory() as session:
            return await RoleRepository(session).list_admin_role_assignments()

    async def assign_role(self, *, user_id: int, role: AdminRole) -> bool:
        async with self.session_factory() as session:
            return await RoleRepository(session).assign_role(user_id=user_id, role=role)

    async def revoke_role(self, *, user_id: int, role: AdminRole) -> bool:
        async with self.session_factory() as session:
            return await RoleRepository(session).revoke_role(user_id=user_id, role=role)

    async def count_users_with_role(self, role: AdminRole) -> int:
        async with self.session_factory() as session:
            return await RoleRepository(session).count_users_with_role(role)


@dataclass(slots=True)
class SqlAlchemyEventReadModelPort(EventReadModelPort):
    session_factory: async_sessionmaker[AsyncSession]
    timezone: tzinfo

    async def list_public_events(self) -> Sequence[PublicEventView]:
        async with self.session_factory() as session:
            stmt = (
                select(EventOccurrenceModel)
                .where(
                    EventOccurrenceModel.status.in_(
                        [EventStatus.PUBLISHED_OPEN, EventStatus.PUBLISHED_FULL]
                    ),
                    EventOccurrenceModel.starts_at > now_utc(),
                )
                .order_by(EventOccurrenceModel.starts_at.asc(), EventOccurrenceModel.id.asc())
            )
            result = await session.execute(stmt)
            return [self._to_public_event(model) for model in result.scalars().all()]

    async def get_public_event(self, event_id: str) -> PublicEventView | None:
        parsed_event_id = _parse_event_id(event_id)
        async with self.session_factory() as session:
            model = await session.get(EventOccurrenceModel, parsed_event_id)
            if model is None:
                return None
            if model.status not in {EventStatus.PUBLISHED_OPEN, EventStatus.PUBLISHED_FULL}:
                return None
            if model.starts_at <= now_utc():
                return None
            return self._to_public_event(model)

    async def list_admin_events(self) -> Sequence[AdminEventView]:
        async with self.session_factory() as session:
            stmt = select(EventOccurrenceModel).order_by(
                EventOccurrenceModel.starts_at.asc(), EventOccurrenceModel.id.asc()
            )
            result = await session.execute(stmt)
            return [self._to_admin_event(model) for model in result.scalars().all()]

    async def get_event_roster(self, event_id: str) -> EventRosterView | None:
        parsed_event_id = _parse_event_id(event_id)
        async with self.session_factory() as session:
            event = await session.get(EventOccurrenceModel, parsed_event_id)
            if event is None:
                return None

            confirmed_stmt = (
                select(ReservationModel, UserModel)
                .join(UserModel, UserModel.id == ReservationModel.user_id)
                .where(
                    ReservationModel.event_id == parsed_event_id,
                    ReservationModel.status == ReservationStatus.CONFIRMED,
                )
                .order_by(ReservationModel.created_at.asc(), ReservationModel.id.asc())
            )
            waitlist_stmt = (
                select(WaitlistEntryModel, UserModel)
                .join(UserModel, UserModel.id == WaitlistEntryModel.user_id)
                .where(
                    WaitlistEntryModel.event_id == parsed_event_id,
                    WaitlistEntryModel.status == WaitlistStatus.ACTIVE,
                )
                .order_by(WaitlistEntryModel.position.asc(), WaitlistEntryModel.id.asc())
            )
            confirmed = await session.execute(confirmed_stmt)
            waitlist = await session.execute(waitlist_stmt)
            return EventRosterView(
                event=self._to_admin_event(event),
                participants=tuple(
                    ParticipantView(
                        display_name=_display_name(user),
                        telegram_user_id=user.telegram_user_id,
                        status=reservation.status,
                        joined_at_local=reservation.created_at.astimezone(self.timezone),
                    )
                    for reservation, user in confirmed.all()
                ),
                waitlist=tuple(
                    ParticipantView(
                        display_name=_display_name(user),
                        telegram_user_id=user.telegram_user_id,
                        status=entry.status,
                        joined_at_local=entry.created_at.astimezone(self.timezone),
                    )
                    for entry, user in waitlist.all()
                ),
            )

    def _to_public_event(self, model: EventOccurrenceModel) -> PublicEventView:
        return PublicEventView(
            event_id=str(model.id),
            tea_name=model.tea_name,
            starts_at_local=model.starts_at.astimezone(self.timezone),
            cancel_deadline_at_local=model.cancel_deadline_at.astimezone(self.timezone),
            capacity=model.capacity,
            reserved_seats=model.reserved_seats,
            description=model.description,
            status=model.status,
            registration_open=model.status
            in {EventStatus.PUBLISHED_OPEN, EventStatus.PUBLISHED_FULL},
        )

    def _to_admin_event(self, model: EventOccurrenceModel) -> AdminEventView:
        return AdminEventView(
            event_id=str(model.id),
            tea_name=model.tea_name,
            starts_at_local=model.starts_at.astimezone(self.timezone),
            capacity=model.capacity,
            reserved_seats=model.reserved_seats,
            status=model.status,
        )


@dataclass(slots=True)
class SqlAlchemyRegistrationCommandPort(RegistrationCommandPort):
    registration_service: RegistrationService
    query_service: EventQueryService
    events: SqlAlchemyEventReadModelPort

    async def register_for_event(
        self,
        *,
        telegram_user_id: int,
        event_id: str,
        idempotency_key: str,
    ) -> RegistrationResult:
        parsed_event_id = _parse_event_id(event_id)
        try:
            result = await self.registration_service.register(
                profile=TelegramProfile(
                    telegram_user_id=telegram_user_id,
                    username=None,
                    first_name=None,
                    last_name=None,
                ),
                event_id=parsed_event_id,
                idempotency_key=idempotency_key,
            )
        except NotFoundError as exc:
            raise LookupError(str(exc)) from exc

        event = await self.events.get_public_event(str(result.event_id))
        if event is None:
            msg = f"Event {result.event_id} not found"
            raise LookupError(msg)
        return RegistrationResult(
            event=event,
            status="confirmed" if result.outcome == "confirmed" else "waitlist",
        )

    async def list_user_registrations(
        self,
        *,
        telegram_user_id: int,
    ) -> Sequence[UserRegistrationView]:
        try:
            registrations = await self.query_service.list_user_active_registrations(
                telegram_user_id
            )
        except NotFoundError:
            return ()

        return tuple(
            UserRegistrationView(
                registration_id=str(registration.event_id),
                event_id=str(registration.event_id),
                tea_name=registration.tea_name,
                starts_at_local=registration.starts_at.astimezone(self.events.timezone),
                cancel_deadline_at_local=registration.cancel_deadline_at.astimezone(
                    self.events.timezone
                ),
                status="waitlist"
                if registration.waitlist_position is not None
                else registration.status,
                can_cancel=registration.waitlist_position is None,
                waitlist_position=registration.waitlist_position,
            )
            for registration in registrations
        )

    async def cancel_registration(
        self,
        *,
        telegram_user_id: int,
        registration_id: str,
        idempotency_key: str,
    ) -> bool:
        parsed_event_id = _parse_event_id(registration_id)
        try:
            await self.registration_service.cancel(
                telegram_user_id=telegram_user_id,
                event_id=parsed_event_id,
                idempotency_key=idempotency_key,
            )
        except ConflictError, NotFoundError:
            return False
        return True


@dataclass(slots=True)
class SqlAlchemyNotificationPreferencePort(NotificationPreferencePort):
    service: NotificationPreferenceService

    async def get_settings(self, *, telegram_user_id: int) -> NotificationSettingsView:
        try:
            settings = await self.service.get_preferences(telegram_user_id)
        except NotFoundError:
            settings = await self.service.set_new_events_enabled(telegram_user_id, False)
        return NotificationSettingsView(enabled=settings.new_events_enabled)

    async def set_enabled(
        self,
        *,
        telegram_user_id: int,
        enabled: bool,
    ) -> NotificationSettingsView:
        settings = await self.service.set_new_events_enabled(telegram_user_id, enabled)
        return NotificationSettingsView(enabled=settings.new_events_enabled)


@dataclass(slots=True)
class SqlAlchemyPublicationWorkflowPort(PublicationWorkflowPort):
    publication_service: PublicationService
    timezone_name: str

    async def publish_single(
        self,
        *,
        actor: Actor,
        preview: EventPreview,
        idempotency_key: str,
    ) -> PublicationReceipt:
        requested = await self.publication_service.publish_single_draft(
            actor=actor,
            draft=preview.normalized,
            timezone_name=self.timezone_name,
            idempotency_key=idempotency_key,
        )
        return PublicationReceipt(
            accepted=True,
            message=(
                "Публикация поставлена в очередь. "
                f"Событие #{requested.event_ids[0]} будет отправлено воркером."
            ),
        )

    async def publish_batch(
        self,
        *,
        actor: Actor,
        previews: Sequence[EventPreview],
        idempotency_key: str,
    ) -> PublicationReceipt:
        requested = await self.publication_service.publish_batch_drafts(
            actor=actor,
            drafts=[preview.normalized for preview in previews],
            timezone_name=self.timezone_name,
            period_label=None,
            idempotency_key=idempotency_key,
        )
        return PublicationReceipt(
            accepted=True,
            message=(
                "Batch-публикация поставлена в очередь. "
                f"Событий к отправке: {len(requested.event_ids)}."
            ),
        )


@dataclass(slots=True)
class SqlAlchemyAdminEventCommandPort(AdminEventCommandPort):
    service: AdminEventService
    timezone: tzinfo

    async def set_event_name(self, *, actor: Actor, event_id: str, tea_name: str) -> str:
        result = await self.service.update_event_fields(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            tea_name=tea_name,
        )
        return result.message

    async def set_event_description(
        self, *, actor: Actor, event_id: str, description: str | None
    ) -> str:
        result = await self.service.update_event_fields(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            description=description,
        )
        return result.message

    async def set_event_start(self, *, actor: Actor, event_id: str, starts_at: str) -> str:
        result = await self.service.update_event_fields(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            starts_at=_parse_datetime(starts_at, self.timezone),
        )
        return result.message

    async def set_event_cancel_deadline(
        self, *, actor: Actor, event_id: str, cancel_deadline_at: str
    ) -> str:
        result = await self.service.update_event_fields(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            cancel_deadline_at=_parse_datetime(cancel_deadline_at, self.timezone),
        )
        return result.message

    async def set_event_capacity(self, *, actor: Actor, event_id: str, capacity: str) -> str:
        try:
            parsed_capacity = int(capacity)
        except ValueError as exc:
            raise ApplicationError("Вместимость должна быть целым числом.") from exc
        result = await self.service.set_capacity(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            capacity=parsed_capacity,
        )
        return result.message

    async def close_registration(self, *, actor: Actor, event_id: str) -> str:
        result = await self.service.close_registration(
            actor=actor, event_id=_parse_admin_event_id(event_id)
        )
        return result.message

    async def reopen_registration(self, *, actor: Actor, event_id: str) -> str:
        result = await self.service.reopen_registration(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
        )
        return result.message

    async def cancel_event(self, *, actor: Actor, event_id: str) -> str:
        result = await self.service.cancel_event(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
        )
        return result.message

    async def add_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, target: str
    ) -> str:
        result = await self.service.add_participant(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            telegram_user_id=_parse_telegram_user_id(telegram_user_id),
            target=target,
        )
        return result.message

    async def remove_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str
    ) -> str:
        result = await self.service.remove_participant(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            telegram_user_id=_parse_telegram_user_id(telegram_user_id),
        )
        return result.message

    async def move_participant(
        self, *, actor: Actor, event_id: str, telegram_user_id: str, target: str
    ) -> str:
        result = await self.service.move_participant(
            actor=actor,
            event_id=_parse_admin_event_id(event_id),
            telegram_user_id=_parse_telegram_user_id(telegram_user_id),
            target=target,
        )
        return result.message


@dataclass(slots=True)
class SqlAlchemyAdminRoleManagementPort(AdminRoleManagementPort):
    service: AdminRoleManagementService

    async def list_assignments(self, *, actor: Actor) -> Sequence[AdminRoleAssignmentView]:
        assignments = await self.service.list_assignments(actor)
        return tuple(
            AdminRoleAssignmentView(
                telegram_user_id=item.telegram_user_id,
                display_name=_display_name_from_parts(
                    telegram_user_id=item.telegram_user_id,
                    username=item.username,
                    first_name=item.first_name,
                    last_name=item.last_name,
                ),
                roles=tuple(sorted(role.value for role in item.roles)),
            )
            for item in assignments
        )

    async def assign_role(self, *, actor: Actor, telegram_user_id: str, role: str) -> str:
        return await self.service.assign_role(
            actor=actor,
            telegram_user_id=_parse_telegram_user_id(telegram_user_id),
            role=_parse_admin_role(role),
        )

    async def revoke_role(self, *, actor: Actor, telegram_user_id: str, role: str) -> str:
        return await self.service.revoke_role(
            actor=actor,
            telegram_user_id=_parse_telegram_user_id(telegram_user_id),
            role=_parse_admin_role(role),
        )


@dataclass(slots=True)
class SqlAlchemySystemSettingsManagementPort(SystemSettingsManagementPort):
    service: SystemSettingsService

    async def get_settings(self, *, actor: Actor) -> ManagedSystemSettingsView:
        settings = await self.service.get_settings(actor)
        return ManagedSystemSettingsView(
            default_cancel_deadline_offset_minutes=settings.default_cancel_deadline_offset_minutes
        )

    async def set_default_cancel_deadline_offset_minutes(
        self, *, actor: Actor, minutes: str
    ) -> ManagedSystemSettingsView:
        settings = await self.service.set_default_cancel_deadline_offset_minutes(
            actor=actor,
            minutes=_parse_non_negative_int(minutes, "default deadline"),
        )
        return ManagedSystemSettingsView(
            default_cancel_deadline_offset_minutes=settings.default_cancel_deadline_offset_minutes
        )
