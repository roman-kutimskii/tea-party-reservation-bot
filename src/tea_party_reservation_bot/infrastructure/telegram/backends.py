from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import tzinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.application.contracts import AdminRoleRepository
from tea_party_reservation_bot.application.dto import TelegramProfile
from tea_party_reservation_bot.application.services import (
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    UserApplicationService,
)
from tea_party_reservation_bot.application.telegram import (
    AdminEventView,
    EventReadModelPort,
    EventRosterView,
    NotificationPreferencePort,
    NotificationSettingsView,
    ParticipantView,
    PublicationReceipt,
    PublicationWorkflowPort,
    PublicEventView,
    RegistrationCommandPort,
    RegistrationResult,
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
from tea_party_reservation_bot.exceptions import ConflictError, NotFoundError
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
                        status=reservation.status,
                        joined_at_local=reservation.created_at.astimezone(self.timezone),
                    )
                    for reservation, user in confirmed.all()
                ),
                waitlist=tuple(
                    ParticipantView(
                        display_name=_display_name(user),
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
    event_persistence_service: EventPersistenceService
    publication_service: PublicationService

    async def publish_single(
        self,
        *,
        actor: Actor,
        preview: EventPreview,
        idempotency_key: str,
    ) -> PublicationReceipt:
        saved = await self.event_persistence_service.save_drafts(actor, [preview.normalized])
        requested = await self.publication_service.request_single_event_publication(
            actor=actor,
            event_id=saved.event_ids[0],
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
        drafts = [preview.normalized for preview in previews]
        saved = await self.event_persistence_service.save_drafts(actor, drafts)
        requested = await self.publication_service.request_batch_publication(
            actor=actor,
            event_ids=list(saved.event_ids),
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
