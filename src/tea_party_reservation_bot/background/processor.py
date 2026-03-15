from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.application.dto import OutboxMessage, StoredEvent, StoredUser
from tea_party_reservation_bot.application.services import PublicationService, SystemClock
from tea_party_reservation_bot.application.telegram import PublicEventView
from tea_party_reservation_bot.domain.enums import EventStatus
from tea_party_reservation_bot.infrastructure.db.models import (
    EventOccurrenceModel,
    PublicationBatchEventModel,
)
from tea_party_reservation_bot.infrastructure.db.repositories import (
    EventRepository,
    OutboxRepository,
    UserRepository,
)
from tea_party_reservation_bot.infrastructure.telegram.deep_links import build_event_deep_link
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    PostingRightsMissingError,
    TelegramGroupPostPayload,
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.logging import get_logger
from tea_party_reservation_bot.time import load_timezone


class TerminalOutboxDispatchError(RuntimeError):
    pass


class RetryableOutboxDispatchError(RuntimeError):
    def __init__(self, message: str, *, payload_updates: dict[str, int] | None = None) -> None:
        super().__init__(message)
        self.payload_updates = payload_updates


@dataclass(slots=True)
class OutboxProcessor:
    session_factory: async_sessionmaker[AsyncSession]
    publication_service: PublicationService
    group_publisher: GroupPublisher
    notifier: TelegramNotifier
    publication_renderer: TelegramPublicationRenderer
    bot_username: str
    group_chat_id: int
    timezone_name: str
    clock: SystemClock
    retry_delay_seconds: int

    async def run_once(self, *, limit: int = 100) -> int:
        async with self.session_factory() as session:
            messages = await OutboxRepository(session).fetch_pending(self.clock.now(), limit=limit)
        return await self._process_messages(messages)

    async def reconcile_once(self, *, limit: int = 100) -> int:
        async with self.session_factory() as session:
            messages = await OutboxRepository(session).fetch_reconciliation_candidates(limit=limit)

        return await self._process_messages(messages)

    async def _process_messages(self, messages: list[OutboxMessage]) -> int:
        logger = get_logger(__name__)
        processed = 0
        for message in messages:
            message_id = self._require_message_id(message)
            try:
                await self._dispatch(message)
            except TerminalOutboxDispatchError as exc:
                logger.warning(
                    "worker.outbox.dispatch_terminal_failure",
                    outbox_event_id=message_id,
                    event_type=message.event_type,
                    error=str(exc),
                )
                async with self.session_factory() as session:
                    await OutboxRepository(session).mark_sent(
                        event_id=message_id,
                        sent_at=self.clock.now(),
                    )
                    await session.commit()
                processed += 1
            except RetryableOutboxDispatchError as exc:
                logger.warning(
                    "worker.outbox.dispatch_failed",
                    outbox_event_id=message_id,
                    event_type=message.event_type,
                    error=str(exc),
                )
                async with self.session_factory() as session:
                    await OutboxRepository(session).mark_failed(
                        event_id=message_id,
                        available_at=self.clock.now()
                        + timedelta(seconds=self.retry_delay_seconds * (message.attempt_count + 1)),
                        last_error=str(exc),
                        payload_updates=exc.payload_updates,
                    )
                    await session.commit()
            except Exception as exc:
                logger.warning(
                    "worker.outbox.dispatch_failed",
                    outbox_event_id=message_id,
                    event_type=message.event_type,
                    error=str(exc),
                )
                async with self.session_factory() as session:
                    await OutboxRepository(session).mark_failed(
                        event_id=message_id,
                        available_at=self.clock.now()
                        + timedelta(seconds=self.retry_delay_seconds * (message.attempt_count + 1)),
                        last_error=str(exc),
                    )
                    await session.commit()
            else:
                async with self.session_factory() as session:
                    await OutboxRepository(session).mark_sent(
                        event_id=message_id,
                        sent_at=self.clock.now(),
                    )
                    await session.commit()
                processed += 1
        return processed

    async def _dispatch(self, message: OutboxMessage) -> None:
        if message.event_type == "publication.requested":
            await self._dispatch_publication(message)
            return
        if message.event_type in {
            "reservation.confirmed",
            "waitlist.joined",
            "waitlist.promoted",
            "reservation.cancelled",
            "waitlist.cancelled",
            "event.updated",
            "event.cancelled",
            "event.announced",
        }:
            await self._dispatch_notification(message)
            return
        msg = f"Unsupported outbox event type: {message.event_type}"
        raise LookupError(msg)

    async def _dispatch_publication(self, message: OutboxMessage) -> None:
        batch_id = int(message.aggregate_id)
        stored_events = await self._load_stored_publication_events(batch_id)
        if not stored_events:
            msg = f"Publication batch {batch_id} has no events"
            raise LookupError(msg)
        event_ids = [event.id for event in stored_events]
        if self._publication_already_reconciled(stored_events):
            return

        reconciliation_chat_id = self._reconciliation_chat_id(message)
        reconciliation_message_id = self._reconciliation_message_id(message)
        if reconciliation_chat_id is not None and reconciliation_message_id is not None:
            await self.publication_service.mark_publication_succeeded(
                batch_id=batch_id,
                event_ids=event_ids,
                chat_id=reconciliation_chat_id,
                message_id=reconciliation_message_id,
            )
            return

        events = self._to_public_event_views(stored_events)
        if len(events) == 1:
            payload = self.publication_renderer.render_published_event_post(
                bot_username=self.bot_username,
                event=events[0],
            )
        else:
            payload = self.publication_renderer.render_published_batch_post(
                bot_username=self.bot_username,
                events=events,
            )
        try:
            telegram_message = await self.group_publisher.send_group_post(
                chat_id=self.group_chat_id,
                payload=payload,
            )
        except PostingRightsMissingError as exc:
            await self.publication_service.mark_publication_failed(
                batch_id=batch_id,
                event_ids=event_ids,
            )
            raise TerminalOutboxDispatchError(str(exc)) from exc
        except Exception as exc:
            await self.publication_service.mark_publication_failed(
                batch_id=batch_id,
                event_ids=event_ids,
            )
            raise TerminalOutboxDispatchError(
                "Publication request failed before Telegram accepted the group post."
            ) from exc
        try:
            await self.publication_service.mark_publication_succeeded(
                batch_id=batch_id,
                event_ids=event_ids,
                chat_id=telegram_message.chat.id,
                message_id=telegram_message.message_id,
            )
        except Exception:
            deleted = False
            try:
                deleted = await self.group_publisher.delete_group_post(
                    chat_id=telegram_message.chat.id,
                    message_id=telegram_message.message_id,
                )
            except Exception:
                deleted = False
            if deleted is False:
                raise RetryableOutboxDispatchError(
                    "Publication was posted to Telegram but local persistence failed; "
                    "reconciliation is required.",
                    payload_updates={
                        "reconciliation_chat_id": telegram_message.chat.id,
                        "reconciliation_message_id": telegram_message.message_id,
                    },
                ) from None
            raise

    async def _dispatch_notification(self, message: OutboxMessage) -> None:
        event = await self._load_event(int(message.payload["event_id"]))
        if message.event_type in {
            "reservation.confirmed",
            "waitlist.joined",
            "waitlist.cancelled",
            "event.updated",
            "event.cancelled",
            "event.announced",
        }:
            telegram_user_id = int(message.payload["telegram_user_id"])
        else:
            user = await self._load_user(int(message.payload["user_id"]))
            telegram_user_id = user.telegram_user_id

        text = self._render_notification_text(
            message.event_type,
            event,
            details=message.payload.get("details"),
        )
        if message.event_type != "event.announced":
            try:
                await self._refresh_group_post(event)
            except PostingRightsMissingError:
                pass
        await self.notifier.send_direct_message(telegram_user_id=telegram_user_id, text=text)

    async def _refresh_group_post(self, event: StoredEvent) -> None:
        if (
            event.telegram_group_chat_id is None
            or event.telegram_group_message_id is None
            or event.publication_batch_id is None
        ):
            return

        stored_events = await self._load_stored_publication_events(event.publication_batch_id)
        if not stored_events:
            return

        events = self._to_public_event_views(stored_events)

        if len(events) == 1:
            payload = self.publication_renderer.render_published_event_post(
                bot_username=self.bot_username,
                event=events[0],
            )
        else:
            payload = self.publication_renderer.render_published_batch_post(
                bot_username=self.bot_username,
                events=events,
            )

        await self.group_publisher.edit_group_post(
            chat_id=event.telegram_group_chat_id,
            message_id=event.telegram_group_message_id,
            payload=payload,
        )

    async def _load_event(self, event_id: int) -> StoredEvent:
        async with self.session_factory() as session:
            repository = EventRepository(session)
            model = await repository.get_by_id(event_id)
            if model is None:
                msg = f"Event {event_id} not found"
                raise LookupError(msg)
            return repository._to_stored_event(model)

    async def _load_user(self, user_id: int) -> StoredUser:
        async with self.session_factory() as session:
            repository = UserRepository(session)
            user = await repository.get_by_id(user_id)
            if user is None:
                msg = f"User {user_id} not found"
                raise LookupError(msg)
            return user

    async def _load_stored_publication_events(self, batch_id: int) -> list[StoredEvent]:
        async with self.session_factory() as session:
            repository = EventRepository(session)
            stmt = (
                select(EventOccurrenceModel)
                .join(
                    PublicationBatchEventModel,
                    PublicationBatchEventModel.event_id == EventOccurrenceModel.id,
                    isouter=True,
                )
                .where(EventOccurrenceModel.publication_batch_id == batch_id)
                .order_by(
                    PublicationBatchEventModel.sort_order.asc(), EventOccurrenceModel.id.asc()
                )
            )
            result = await session.execute(stmt)
            return [repository._to_stored_event(model) for model in result.scalars().all()]

    def _to_public_event_views(self, events: list[StoredEvent]) -> list[PublicEventView]:
        timezone = load_timezone(self.timezone_name)
        return [
            PublicEventView(
                event_id=str(event.id),
                tea_name=event.tea_name,
                starts_at_local=event.starts_at.astimezone(timezone),
                cancel_deadline_at_local=event.cancel_deadline_at.astimezone(timezone),
                capacity=event.capacity,
                reserved_seats=event.reserved_seats,
                description=event.description,
                status=event.status,
                registration_open=event.status
                in {EventStatus.PUBLISHED_OPEN, EventStatus.PUBLISHED_FULL},
            )
            for event in events
        ]

    @staticmethod
    def _publication_already_reconciled(events: list[StoredEvent]) -> bool:
        if not events:
            return False
        chat_ids = {event.telegram_group_chat_id for event in events}
        message_ids = {event.telegram_group_message_id for event in events}
        return (
            None not in chat_ids
            and None not in message_ids
            and len(chat_ids) == 1
            and len(message_ids) == 1
            and all(event.published_at is not None for event in events)
        )

    @staticmethod
    def _reconciliation_chat_id(message: OutboxMessage) -> int | None:
        raw_value = message.payload.get("reconciliation_chat_id")
        if raw_value is None:
            return None
        return int(raw_value)

    @staticmethod
    def _reconciliation_message_id(message: OutboxMessage) -> int | None:
        raw_value = message.payload.get("reconciliation_message_id")
        if raw_value is None:
            return None
        return int(raw_value)

    @staticmethod
    def _require_message_id(message: OutboxMessage) -> int:
        if message.id is None:
            msg = f"Outbox message for {message.event_type} is missing an id"
            raise LookupError(msg)
        return message.id

    def _render_notification_text(
        self, event_type: str, event: StoredEvent, *, details: str | None = None
    ) -> str:
        starts_at_local = event.starts_at.astimezone(load_timezone(self.timezone_name))
        event_label = f"{event.tea_name}\n{starts_at_local:%d.%m.%Y %H:%M}"
        templates = {
            "reservation.confirmed": (
                f"Вы записаны на дегустацию. За вами подтверждено 1 место.\n{event_label}"
            ),
            "waitlist.joined": (
                f"Вы добавлены в лист ожидания. Это еще не подтвержденное место.\n{event_label}"
            ),
            "waitlist.promoted": (
                f"Освободилось место. Теперь за вами подтверждено 1 место.\n{event_label}"
            ),
            "reservation.cancelled": f"Ваша запись отменена.\n{event_label}",
            "waitlist.cancelled": f"Вы удалены из листа ожидания.\n{event_label}",
            "event.updated": f"Событие изменено.\n{event_label}",
            "event.cancelled": f"Событие отменено.\n{event_label}",
            "event.announced": (
                "Анонс новой дегустации.\n"
                f"{event_label}\n"
                "Записаться: "
                f"{build_event_deep_link(bot_username=self.bot_username, event_id=str(event.id))}"
            ),
        }
        message = templates[event_type]
        if details:
            message = f"{message}\n{details}"
        return message


class GroupPublisher(Protocol):
    async def send_group_post(
        self, *, chat_id: int, payload: TelegramGroupPostPayload
    ) -> Message: ...

    async def delete_group_post(self, *, chat_id: int, message_id: int) -> bool: ...

    async def edit_group_post(
        self,
        *,
        chat_id: int,
        message_id: int,
        payload: TelegramGroupPostPayload,
    ) -> Message: ...


class TelegramNotifier(Protocol):
    async def send_direct_message(self, *, telegram_user_id: int, text: str) -> Message: ...
