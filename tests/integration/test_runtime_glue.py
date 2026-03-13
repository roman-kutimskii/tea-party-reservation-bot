from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.application.services import (
    AdminAccessService,
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    SystemClock,
    UserApplicationService,
)
from tea_party_reservation_bot.application.telegram import TelegramUserProfile
from tea_party_reservation_bot.background.processor import OutboxProcessor
from tea_party_reservation_bot.domain.enums import CancelDeadlineSource, EventStatus
from tea_party_reservation_bot.domain.events import EventDraft, EventPreview
from tea_party_reservation_bot.infrastructure.db.models import (
    EventOccurrenceModel,
    OutboxEventModel,
)
from tea_party_reservation_bot.infrastructure.telegram.backends import (
    SqlAlchemyAdminRoleRepository,
    SqlAlchemyEventReadModelPort,
    SqlAlchemyNotificationPreferencePort,
    SqlAlchemyPublicationWorkflowPort,
    SqlAlchemyRegistrationCommandPort,
    SqlAlchemyTelegramUserSyncPort,
)
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramGroupPostPayload,
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.time import load_timezone


@dataclass(slots=True)
class FakeChat:
    id: int


@dataclass(slots=True)
class FakeMessage:
    chat: FakeChat
    message_id: int


@dataclass(slots=True)
class FakeGroupPublisher:
    messages: list[tuple[int, str]]

    async def send_group_post(
        self, *, chat_id: int, payload: TelegramGroupPostPayload
    ) -> FakeMessage:
        self.messages.append((chat_id, payload.text))
        return FakeMessage(chat=FakeChat(chat_id), message_id=777)


@dataclass(slots=True)
class FakeNotifier:
    messages: list[tuple[int, str]]

    async def send_direct_message(self, *, telegram_user_id: int, text: str) -> FakeMessage:
        self.messages.append((telegram_user_id, text))
        return FakeMessage(chat=FakeChat(telegram_user_id), message_id=len(self.messages))


def _services(
    services: dict[str, object],
) -> tuple[
    UserApplicationService,
    AdminAccessService,
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
]:
    return (
        cast(UserApplicationService, services["user"]),
        cast(AdminAccessService, services["admin_access"]),
        cast(EventPersistenceService, services["events"]),
        cast(EventQueryService, services["query"]),
        cast(NotificationPreferenceService, services["notifications"]),
        cast(PublicationService, services["publication"]),
        cast(RegistrationService, services["registration"]),
    )


@pytest.mark.asyncio
async def test_db_backed_bot_ports_and_worker_process_publication_request(
    services: dict[str, object],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    (
        user_service,
        admin_access,
        event_service,
        query_service,
        notification_service,
        publication_service,
        registration_service,
    ) = _services(services)
    timezone = load_timezone("Europe/Moscow")
    event_read_model = SqlAlchemyEventReadModelPort(
        session_factory=session_factory, timezone=timezone
    )
    registration_port = SqlAlchemyRegistrationCommandPort(
        registration_service=registration_service,
        query_service=query_service,
        events=event_read_model,
    )
    publication_port = SqlAlchemyPublicationWorkflowPort(event_service, publication_service)
    notification_port = SqlAlchemyNotificationPreferencePort(notification_service)
    user_sync = SqlAlchemyTelegramUserSyncPort(user_service)

    await user_sync.upsert_user(
        TelegramUserProfile(
            telegram_user_id=2001,
            username="guest",
            first_name="Guest",
            last_name=None,
        )
    )
    actor = await admin_access.load_actor(1000)
    start = datetime.now(tz=UTC) + timedelta(days=5)
    preview = EventPreview(
        normalized=EventDraft(
            tea_name="Шуй Сянь",
            description="Тестовая публикация",
            starts_at_local=start.astimezone(timezone),
            starts_at_utc=start,
            capacity=8,
            cancel_deadline_source=CancelDeadlineSource.DEFAULT,
            cancel_deadline_at_local=(start - timedelta(hours=4)).astimezone(timezone),
            cancel_deadline_at_utc=start - timedelta(hours=4),
        ),
        block_number=1,
    )

    receipt = await publication_port.publish_single(
        actor=actor,
        preview=preview,
        idempotency_key="publish-port-single",
    )

    assert receipt.accepted is True
    public_events = await event_read_model.list_public_events()
    assert public_events == []

    processor = OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=FakeGroupPublisher(messages=[]),
        notifier=FakeNotifier(messages=[]),
        publication_renderer=TelegramPublicationRenderer(),
        bot_username="tea_party_bot",
        group_chat_id=-100123,
        timezone_name="Europe/Moscow",
        clock=SystemClock(),
        retry_delay_seconds=1,
    )
    processed = await processor.run_once(limit=10)

    assert processed == 1
    public_events = await event_read_model.list_public_events()
    assert len(public_events) == 1
    assert public_events[0].tea_name == "Шуй Сянь"

    async with session_factory() as session:
        event = (await session.execute(select(EventOccurrenceModel))).scalar_one()
        outbox = (await session.execute(select(OutboxEventModel))).scalar_one()
        assert event.status == EventStatus.PUBLISHED_OPEN
        assert event.telegram_group_message_id == 777
        assert outbox.sent_at is not None

    settings = await notification_port.set_enabled(telegram_user_id=2001, enabled=True)
    assert settings.enabled is True
    listed = await registration_port.list_user_registrations(telegram_user_id=2001)
    assert listed == ()


@pytest.mark.asyncio
async def test_db_backed_ports_show_real_registrations_roster_and_notifications(
    services: dict[str, object],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    (
        user_service,
        _admin_access,
        event_service,
        query_service,
        _notification_service,
        publication_service,
        registration_service,
    ) = _services(services)
    timezone = load_timezone("Europe/Moscow")
    event_read_model = SqlAlchemyEventReadModelPort(
        session_factory=session_factory, timezone=timezone
    )
    registration_port = SqlAlchemyRegistrationCommandPort(
        registration_service=registration_service,
        query_service=query_service,
        events=event_read_model,
    )
    user_sync = SqlAlchemyTelegramUserSyncPort(user_service)
    roles = SqlAlchemyAdminRoleRepository(session_factory)

    actor = await roles.get_actor(1000)
    start = datetime.now(tz=UTC) + timedelta(days=3)
    draft = EventDraft(
        tea_name="Да Хун Пао",
        description="Вечерняя дегустация",
        starts_at_local=start.astimezone(timezone),
        starts_at_utc=start,
        capacity=1,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=(start - timedelta(hours=4)).astimezone(timezone),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key="publish-2",
    )

    processor = OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=FakeGroupPublisher(messages=[]),
        notifier=FakeNotifier(messages=[]),
        publication_renderer=TelegramPublicationRenderer(),
        bot_username="tea_party_bot",
        group_chat_id=-100123,
        timezone_name="Europe/Moscow",
        clock=SystemClock(),
        retry_delay_seconds=1,
    )
    await processor.run_once(limit=10)

    await user_sync.upsert_user(
        TelegramUserProfile(
            telegram_user_id=3001,
            username="u1",
            first_name="One",
            last_name=None,
        )
    )
    await user_sync.upsert_user(
        TelegramUserProfile(
            telegram_user_id=3002,
            username="u2",
            first_name="Two",
            last_name=None,
        )
    )

    first = await registration_port.register_for_event(
        telegram_user_id=3001,
        event_id=str(saved.event_ids[0]),
        idempotency_key="r1",
    )
    second = await registration_port.register_for_event(
        telegram_user_id=3002,
        event_id=str(saved.event_ids[0]),
        idempotency_key="r2",
    )

    assert first.status == "confirmed"
    assert second.status == "waitlist"

    my_items = await registration_port.list_user_registrations(telegram_user_id=3002)
    assert len(my_items) == 1
    assert my_items[0].waitlist_position == 1

    roster = await event_read_model.get_event_roster(str(saved.event_ids[0]))
    assert roster is not None
    assert len(roster.participants) == 1
    assert len(roster.waitlist) == 1

    cancelled = await registration_port.cancel_registration(
        telegram_user_id=3001,
        registration_id=str(saved.event_ids[0]),
        idempotency_key="cancel-1",
    )
    assert cancelled is True

    notifier = FakeNotifier(messages=[])
    processor = OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=FakeGroupPublisher(messages=[]),
        notifier=notifier,
        publication_renderer=TelegramPublicationRenderer(),
        bot_username="tea_party_bot",
        group_chat_id=-100123,
        timezone_name="Europe/Moscow",
        clock=SystemClock(),
        retry_delay_seconds=1,
    )
    processed = await processor.run_once(limit=20)

    assert processed >= 4
    assert {message[0] for message in notifier.messages} == {3001, 3002}
    assert any("лист ожидания" in text for _, text in notifier.messages)
    assert any("подтверждена" in text for _, text in notifier.messages)

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, saved.event_ids[0])
        outbox_rows = (await session.execute(select(OutboxEventModel))).scalars().all()
        assert event is not None
        assert event.status == EventStatus.PUBLISHED_FULL
        assert all(row.sent_at is not None for row in outbox_rows)
        assert requested.batch_id is not None
        batch_status = await session.scalar(
            select(EventOccurrenceModel.status).where(EventOccurrenceModel.id == saved.event_ids[0])
        )
        assert batch_status == EventStatus.PUBLISHED_FULL
