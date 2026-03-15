from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy.exc import IntegrityError

from tea_party_reservation_bot.application.contracts import AuthorizationService, Clock, UnitOfWork
from tea_party_reservation_bot.application.dto import (
    ActiveRegistrationView,
    NotificationPreferenceView,
    OutboxMessage,
    PublicationIntent,
    RosterEntryView,
    StoredEvent,
    StoredUser,
    TelegramProfile,
)
from tea_party_reservation_bot.domain.enums import (
    EventStatus,
    Permission,
    PublicationBatchStatus,
    ReservationStatus,
    WaitlistStatus,
)
from tea_party_reservation_bot.domain.events import EventDraft, EventPreview
from tea_party_reservation_bot.domain.parsing import AdminEventInputParser
from tea_party_reservation_bot.domain.rbac import Actor
from tea_party_reservation_bot.exceptions import ApplicationError, ConflictError, NotFoundError
from tea_party_reservation_bot.time import now_utc


class SystemClock(Clock):
    def now(self) -> datetime:
        return now_utc()


@dataclass(slots=True, frozen=True)
class RegistrationResult:
    event_id: int
    user_id: int
    outcome: str
    reservation_id: int | None
    waitlist_entry_id: int | None
    message: str


@dataclass(slots=True, frozen=True)
class CancellationResult:
    event_id: int
    user_id: int
    cancelled_reservation_id: int
    promoted_user_id: int | None
    promoted_telegram_user_id: int | None
    message: str


@dataclass(slots=True, frozen=True)
class DraftSaveResult:
    event_ids: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class PublicationRequestResult:
    batch_id: int | None
    event_ids: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class PublicationStateChangeResult:
    batch_id: int
    event_ids: tuple[int, ...]
    status: str


IdempotentResult = (
    RegistrationResult
    | CancellationResult
    | DraftSaveResult
    | PublicationRequestResult
    | PublicationStateChangeResult
)


@dataclass(slots=True)
class EventDraftingService:
    parser: AdminEventInputParser
    authorization_service: AuthorizationService
    timezone_name: str

    def preview_from_text(self, actor: Actor, raw_text: str) -> list[EventPreview]:
        self.authorization_service.require(actor, Permission.CREATE_DRAFT)
        return self.parser.parse_many(raw_text, timezone_name=self.timezone_name)


@dataclass(slots=True)
class UserApplicationService:
    uow_factory: Callable[[], UnitOfWork]

    async def ensure_user(self, profile: TelegramProfile) -> StoredUser:
        async with self.uow_factory() as uow:
            return await uow.users.ensure_from_telegram_profile(profile)


@dataclass(slots=True)
class AdminAccessService:
    uow_factory: Callable[[], UnitOfWork]

    async def load_actor(self, telegram_user_id: int) -> Actor:
        async with self.uow_factory() as uow:
            return await uow.roles.get_actor(telegram_user_id)


@dataclass(slots=True)
class EventPersistenceService:
    uow_factory: Callable[[], UnitOfWork]
    authorization_service: AuthorizationService
    timezone_name: str

    async def save_drafts(self, actor: Actor, drafts: list[EventDraft]) -> DraftSaveResult:
        self.authorization_service.require(actor, Permission.CREATE_DRAFT)
        async with self.uow_factory() as uow:
            admin_user = await _require_existing_user(uow, actor.telegram_user_id)
            event_ids = await uow.events.save_drafts(
                drafts,
                actor_user_id=admin_user.id,
                timezone_name=self.timezone_name,
            )
            await uow.audit_log.append(
                actor_user_id=admin_user.id,
                action="event_drafts_saved",
                target_type="event_occurrence",
                target_id=",".join(str(event_id) for event_id in event_ids),
                payload_json={"event_ids": event_ids},
            )
            return DraftSaveResult(event_ids=tuple(event_ids))


@dataclass(slots=True)
class PublicationService:
    uow_factory: Callable[[], UnitOfWork]
    authorization_service: AuthorizationService
    clock: Clock

    async def request_single_event_publication(
        self,
        *,
        actor: Actor,
        event_id: int,
        idempotency_key: str,
    ) -> PublicationRequestResult:
        self.authorization_service.require(actor, Permission.PUBLISH_EVENT)

        async def operation(uow: UnitOfWork) -> PublicationRequestResult:
            admin_user = await _require_existing_user(uow, actor.telegram_user_id)
            intent = await uow.publications.create_single_event_publication_intent(
                event_id=event_id,
                actor_user_id=admin_user.id,
            )
            await _enqueue_publication_outbox(
                uow,
                clock=self.clock,
                intent=intent,
                publication_kind="single",
            )
            await uow.audit_log.append(
                actor_user_id=admin_user.id,
                action="single_event_publication_requested",
                target_type="publication_batch",
                target_id=str(intent.batch_id),
                payload_json={"event_ids": list(intent.event_ids)},
            )
            return PublicationRequestResult(batch_id=intent.batch_id, event_ids=intent.event_ids)

        return await _run_idempotent(
            self.uow_factory,
            source="publish_single_event",
            idempotency_key=idempotency_key,
            operation=operation,
        )

    async def request_batch_publication(
        self,
        *,
        actor: Actor,
        event_ids: list[int],
        period_label: str | None,
        idempotency_key: str,
    ) -> PublicationRequestResult:
        self.authorization_service.require(actor, Permission.PUBLISH_EVENT)

        async def operation(uow: UnitOfWork) -> PublicationRequestResult:
            admin_user = await _require_existing_user(uow, actor.telegram_user_id)
            intent = await uow.publications.create_batch_publication_intent(
                event_ids=event_ids,
                actor_user_id=admin_user.id,
                period_label=period_label,
            )
            await _enqueue_publication_outbox(
                uow,
                clock=self.clock,
                intent=intent,
                publication_kind="batch",
            )
            await uow.audit_log.append(
                actor_user_id=admin_user.id,
                action="batch_publication_requested",
                target_type="publication_batch",
                target_id=str(intent.batch_id),
                payload_json={"event_ids": list(intent.event_ids), "period_label": period_label},
            )
            return PublicationRequestResult(batch_id=intent.batch_id, event_ids=intent.event_ids)

        return await _run_idempotent(
            self.uow_factory,
            source="publish_event_batch",
            idempotency_key=idempotency_key,
            operation=operation,
        )

    async def mark_publication_succeeded(
        self,
        *,
        batch_id: int,
        event_ids: list[int],
        chat_id: int,
        message_id: int,
    ) -> PublicationStateChangeResult:
        async with self.uow_factory() as uow:
            stored_event_ids = await uow.events.list_publication_event_ids(batch_id)
            if set(stored_event_ids) != set(event_ids):
                raise ApplicationError("Состав публикации не совпадает с данными в базе.")
            published_at = self.clock.now()
            await uow.publications.mark_batch_state(
                batch_id=batch_id,
                status=PublicationBatchStatus.PUBLISHED,
                published_at=published_at,
                chat_id=chat_id,
                message_id=message_id,
            )
            await uow.events.mark_publication_succeeded(
                event_ids=event_ids,
                chat_id=chat_id,
                message_id=message_id,
                published_at=published_at,
            )
            return PublicationStateChangeResult(
                batch_id=batch_id,
                event_ids=stored_event_ids,
                status=PublicationBatchStatus.PUBLISHED,
            )

    async def mark_publication_failed(
        self, *, batch_id: int, event_ids: list[int]
    ) -> PublicationStateChangeResult:
        async with self.uow_factory() as uow:
            stored_event_ids = await uow.events.list_publication_event_ids(batch_id)
            if set(stored_event_ids) != set(event_ids):
                raise ApplicationError("Состав публикации не совпадает с данными в базе.")
            await uow.publications.mark_batch_state(
                batch_id=batch_id, status=PublicationBatchStatus.FAILED
            )
            await uow.events.mark_publication_failed(event_ids=stored_event_ids)
            return PublicationStateChangeResult(
                batch_id=batch_id,
                event_ids=stored_event_ids,
                status=PublicationBatchStatus.FAILED,
            )


@dataclass(slots=True)
class EventQueryService:
    uow_factory: Callable[[], UnitOfWork]
    authorization_service: AuthorizationService
    clock: Clock

    async def list_published_upcoming_events(self) -> list[StoredEvent]:
        async with self.uow_factory() as uow:
            return await uow.events.list_published_upcoming(self.clock.now())

    async def list_user_active_registrations(
        self, telegram_user_id: int
    ) -> list[ActiveRegistrationView]:
        async with self.uow_factory() as uow:
            user = await _require_existing_user(uow, telegram_user_id)
            return await uow.events.list_active_registrations_for_user(user.id)

    async def get_admin_event_roster(self, actor: Actor, event_id: int) -> list[RosterEntryView]:
        self.authorization_service.require(actor, Permission.VIEW_EVENTS)
        async with self.uow_factory() as uow:
            return await uow.events.get_roster(event_id)


@dataclass(slots=True)
class NotificationPreferenceService:
    uow_factory: Callable[[], UnitOfWork]

    async def get_preferences(self, telegram_user_id: int) -> NotificationPreferenceView:
        async with self.uow_factory() as uow:
            user = await _require_existing_user(uow, telegram_user_id)
            return await uow.notifications.get_or_create(user.id)

    async def set_new_events_enabled(
        self, telegram_user_id: int, enabled: bool
    ) -> NotificationPreferenceView:
        async with self.uow_factory() as uow:
            user = await _require_existing_user(uow, telegram_user_id)
            return await uow.notifications.set_enabled(user.id, enabled)


@dataclass(slots=True)
class RegistrationService:
    uow_factory: Callable[[], UnitOfWork]
    clock: Clock
    authorization_service: AuthorizationService | None = None

    async def register(
        self,
        *,
        profile: TelegramProfile,
        event_id: int,
        idempotency_key: str,
        source: str = "telegram",
    ) -> RegistrationResult:
        async def operation(uow: UnitOfWork) -> RegistrationResult:
            user = await uow.users.ensure_from_telegram_profile(profile)
            event = await uow.events.get_by_id(event_id, for_update=True)
            if event is None:
                raise NotFoundError("Событие не найдено.")

            now = self.clock.now()
            _ensure_registration_allowed(event, now)

            active_reservation = await uow.registrations.get_active_reservation(
                event_id=event_id, user_id=user.id
            )
            if active_reservation is not None:
                raise ConflictError("У Вас уже есть активная запись на это событие.")

            active_waitlist_entry = await uow.registrations.get_active_waitlist_entry(
                event_id=event_id, user_id=user.id
            )
            if active_waitlist_entry is not None:
                raise ConflictError("Вы уже находитесь в листе ожидания для этого события.")

            if event.reserved_seats < event.capacity:
                reservation = await uow.registrations.create_confirmed_reservation(
                    event_id=event.id,
                    user_id=user.id,
                    source=source,
                )
                event.reserved_seats += 1
                event.sync_status_from_capacity()
                result = RegistrationResult(
                    event_id=event.id,
                    user_id=user.id,
                    outcome="confirmed",
                    reservation_id=reservation.id,
                    waitlist_entry_id=None,
                    message="Вы записаны.",
                )
                outbox_event_type = "reservation.confirmed"
            else:
                waitlist_entry = await uow.registrations.create_waitlist_entry(
                    event_id=event.id,
                    user_id=user.id,
                )
                event.sync_status_from_capacity()
                result = RegistrationResult(
                    event_id=event.id,
                    user_id=user.id,
                    outcome="waitlisted",
                    reservation_id=None,
                    waitlist_entry_id=waitlist_entry.id,
                    message="Вы в листе ожидания.",
                )
                outbox_event_type = "waitlist.joined"

            await uow.outbox.enqueue(
                OutboxMessage(
                    aggregate_type="event_occurrence",
                    aggregate_id=str(event.id),
                    event_type=outbox_event_type,
                    payload={
                        "event_id": event.id,
                        "telegram_user_id": profile.telegram_user_id,
                        "user_id": user.id,
                        "outcome": result.outcome,
                    },
                    available_at=now,
                )
            )
            return result

        return await _run_idempotent(
            self.uow_factory,
            source="register",
            idempotency_key=idempotency_key,
            operation=operation,
        )

    async def cancel(
        self,
        *,
        telegram_user_id: int,
        event_id: int,
        idempotency_key: str,
        override_deadline: bool = False,
        actor: Actor | None = None,
    ) -> CancellationResult:
        if override_deadline:
            if actor is None or self.authorization_service is None:
                raise ApplicationError(
                    "Для административной отмены требуется авторизованный администратор."
                )
            self.authorization_service.require(actor, Permission.MANAGE_REGISTRATIONS)

        async def operation(uow: UnitOfWork) -> CancellationResult:
            user = await _require_existing_user(uow, telegram_user_id)
            event = await uow.events.get_by_id(event_id, for_update=True)
            if event is None:
                raise NotFoundError("Событие не найдено.")
            reservation = await uow.registrations.get_active_reservation(
                event_id=event_id, user_id=user.id
            )
            if reservation is None:
                raise NotFoundError("Активная запись не найдена.")
            now = self.clock.now()
            if now > event.cancel_deadline_at and not override_deadline:
                raise ConflictError("Срок самостоятельной отмены уже истек.")

            reservation.status = ReservationStatus.CANCELLED
            reservation.cancelled_at = now
            event.reserved_seats -= 1
            event.sync_status_from_capacity()

            promoted_user_id: int | None = None
            promoted_telegram_user_id: int | None = None
            next_waitlist_entry = await uow.registrations.next_waitlist_entry_for_promotion(
                event_id=event.id
            )
            if next_waitlist_entry is not None and event.reserved_seats < event.capacity:
                next_waitlist_entry.status = WaitlistStatus.PROMOTED
                next_waitlist_entry.promoted_at = now
                promoted_reservation = await uow.registrations.create_confirmed_reservation(
                    event_id=event.id,
                    user_id=next_waitlist_entry.user_id,
                    source="waitlist_promotion",
                    promoted_from_waitlist_entry_id=next_waitlist_entry.id,
                )
                event.reserved_seats += 1
                event.sync_status_from_capacity()
                promoted_user_id = next_waitlist_entry.user_id
                if promoted_user_id is not None:
                    promoted_user = await uow.users.get_by_id(promoted_user_id)
                    if promoted_user is not None:
                        promoted_telegram_user_id = promoted_user.telegram_user_id
                await uow.outbox.enqueue(
                    OutboxMessage(
                        aggregate_type="event_occurrence",
                        aggregate_id=str(event.id),
                        event_type="waitlist.promoted",
                        payload={
                            "event_id": event.id,
                            "reservation_id": promoted_reservation.id,
                            "user_id": promoted_user_id,
                        },
                        available_at=now,
                    )
                )

            await uow.outbox.enqueue(
                OutboxMessage(
                    aggregate_type="event_occurrence",
                    aggregate_id=str(event.id),
                    event_type="reservation.cancelled",
                    payload={
                        "event_id": event.id,
                        "user_id": user.id,
                        "reservation_id": reservation.id,
                    },
                    available_at=now,
                )
            )

            return CancellationResult(
                event_id=event.id,
                user_id=user.id,
                cancelled_reservation_id=reservation.id,
                promoted_user_id=promoted_user_id,
                promoted_telegram_user_id=promoted_telegram_user_id,
                message="Запись отменена.",
            )

        return await _run_idempotent(
            self.uow_factory,
            source="cancel",
            idempotency_key=idempotency_key,
            operation=operation,
        )


def _ensure_registration_allowed(event: Any, now: datetime) -> None:
    if event.status not in {EventStatus.PUBLISHED_OPEN, EventStatus.PUBLISHED_FULL}:
        raise ConflictError("Регистрация на это событие сейчас недоступна.")
    if now >= event.starts_at:
        raise ConflictError("Событие уже началось.")


async def _require_existing_user(uow: UnitOfWork, telegram_user_id: int) -> StoredUser:
    user = await uow.users.get_by_telegram_user_id(telegram_user_id)
    if user is None:
        raise NotFoundError("Пользователь не найден.")
    return user


async def _enqueue_publication_outbox(
    uow: UnitOfWork,
    *,
    clock: Clock,
    intent: PublicationIntent,
    publication_kind: str,
) -> None:
    await uow.outbox.enqueue(
        OutboxMessage(
            aggregate_type="publication_batch",
            aggregate_id=str(intent.batch_id),
            event_type="publication.requested",
            payload={"event_ids": list(intent.event_ids), "kind": publication_kind},
            available_at=clock.now(),
        )
    )


async def _run_idempotent[ResultT: IdempotentResult](
    uow_factory: Callable[[], UnitOfWork],
    *,
    source: str,
    idempotency_key: str,
    operation: Callable[[UnitOfWork], Awaitable[ResultT]],
) -> ResultT:
    async with uow_factory() as uow:
        processed = await uow.idempotency.get(source=source, idempotency_key=idempotency_key)
        if processed is not None:
            payload = uow.idempotency.load_result(processed.result_ref)
            if payload is None:
                raise ApplicationError("Идемпотентный результат поврежден.")
            return cast(ResultT, _hydrate_result(payload))

    try:
        async with uow_factory() as uow:
            result = await operation(uow)
            await uow.idempotency.record(
                source=source,
                idempotency_key=idempotency_key,
                result_ref=uow.idempotency.dump_result(asdict(result)),
            )
            return result
    except IntegrityError as err:
        async with uow_factory() as uow:
            processed = await uow.idempotency.get(source=source, idempotency_key=idempotency_key)
            if processed is None:
                raise
            payload = uow.idempotency.load_result(processed.result_ref)
            if payload is None:
                raise ApplicationError("Идемпотентный результат поврежден.") from err
            return cast(ResultT, _hydrate_result(payload))


def _hydrate_result(payload: dict[str, Any]) -> IdempotentResult:
    if "outcome" in payload:
        return RegistrationResult(**payload)
    if "cancelled_reservation_id" in payload:
        return CancellationResult(**payload)
    if "batch_id" in payload and "status" in payload:
        return PublicationStateChangeResult(**payload)
    if "batch_id" in payload and "event_ids" in payload:
        payload["event_ids"] = tuple(payload["event_ids"])
        return PublicationRequestResult(**payload)
    if "event_ids" in payload:
        payload["event_ids"] = tuple(payload["event_ids"])
        return DraftSaveResult(**payload)
    raise ApplicationError("Неизвестный формат идемпотентного результата.")
