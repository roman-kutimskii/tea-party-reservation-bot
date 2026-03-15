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
    TelegramGroupPostPayload,
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.logging import get_logger
from tea_party_reservation_bot.time import load_timezone


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
        logger = get_logger(__name__)
        async with self.session_factory() as session:
            messages = await OutboxRepository(session).fetch_pending(self.clock.now(), limit=limit)

        processed = 0
        for message in messages:
            message_id = self._require_message_id(message)
            try:
                await self._dispatch(message)
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
        events = await self._load_publication_events(batch_id)
        if not events:
            msg = f"Publication batch {batch_id} has no events"
            raise LookupError(msg)
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
        except Exception:
            await self.publication_service.mark_publication_failed(
                batch_id=batch_id,
                event_ids=[int(event.event_id) for event in events],
            )
            raise
        await self.publication_service.mark_publication_succeeded(
            batch_id=batch_id,
            event_ids=[int(event.event_id) for event in events],
            chat_id=telegram_message.chat.id,
            message_id=telegram_message.message_id,
        )

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
        await self.notifier.send_direct_message(telegram_user_id=telegram_user_id, text=text)
        if message.event_type != "event.announced":
            await self._refresh_group_post(event)

    async def _refresh_group_post(self, event: StoredEvent) -> None:
        if (
            event.telegram_group_chat_id is None
            or event.telegram_group_message_id is None
            or event.publication_batch_id is None
        ):
            return

        events = await self._load_publication_events(event.publication_batch_id)
        if not events:
            return

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

    async def _load_publication_events(self, batch_id: int) -> list[PublicEventView]:
        timezone = load_timezone(self.timezone_name)
        async with self.session_factory() as session:
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
            models = result.scalars().all()
            return [
                PublicEventView(
                    event_id=str(model.id),
                    tea_name=model.tea_name,
                    starts_at_local=model.starts_at.astimezone(timezone),
                    cancel_deadline_at_local=model.cancel_deadline_at.astimezone(timezone),
                    capacity=model.capacity,
                    reserved_seats=model.reserved_seats,
                    description=model.description,
                    status=model.status,
                    registration_open=model.status
                    in {EventStatus.PUBLISHED_OPEN, EventStatus.PUBLISHED_FULL},
                )
                for model in models
            ]

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
            "reservation.confirmed": f"Вы записаны на дегустацию.\n{event_label}",
            "waitlist.joined": f"Вы добавлены в лист ожидания.\n{event_label}",
            "waitlist.promoted": f"Освободилось место. Ваша запись подтверждена.\n{event_label}",
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

    async def edit_group_post(
        self,
        *,
        chat_id: int,
        message_id: int,
        payload: TelegramGroupPostPayload,
    ) -> Message: ...


class TelegramNotifier(Protocol):
    async def send_direct_message(self, *, telegram_user_id: int, text: str) -> Message: ...
