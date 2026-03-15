from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.application.contracts import UnitOfWork
from tea_party_reservation_bot.application.dto import TelegramProfile
from tea_party_reservation_bot.application.security import DomainAuthorizationService
from tea_party_reservation_bot.application.services import (
    AdminAccessService,
    AdminAuditService,
    AdminEventService,
    AdminRoleManagementService,
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    SystemClock,
    SystemSettingsService,
    UserApplicationService,
)
from tea_party_reservation_bot.application.telegram import (
    TelegramBotApplicationService,
    TelegramUserProfile,
)
from tea_party_reservation_bot.background.processor import OutboxProcessor
from tea_party_reservation_bot.domain.enums import CancelDeadlineSource, EventStatus
from tea_party_reservation_bot.domain.events import EventDraft, EventPreview
from tea_party_reservation_bot.infrastructure.db.models import (
    AdminAuditLogModel,
    EventOccurrenceModel,
    OutboxEventModel,
)
from tea_party_reservation_bot.infrastructure.db.uow import SqlAlchemyUnitOfWork
from tea_party_reservation_bot.infrastructure.telegram.backends import (
    SqlAlchemyAdminRoleManagementPort,
    SqlAlchemyAdminRoleRepository,
    SqlAlchemyEventReadModelPort,
    SqlAlchemyNotificationPreferencePort,
    SqlAlchemyPublicationWorkflowPort,
    SqlAlchemyRegistrationCommandPort,
    SqlAlchemySystemSettingsManagementPort,
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
    edited_messages: list[tuple[int, int, str]]

    async def send_group_post(self, *, chat_id: int, payload: TelegramGroupPostPayload) -> Message:
        self.messages.append((chat_id, payload.text))
        return cast(Any, FakeMessage(chat=FakeChat(chat_id), message_id=777))

    async def edit_group_post(
        self, *, chat_id: int, message_id: int, payload: TelegramGroupPostPayload
    ) -> Message:
        self.edited_messages.append((chat_id, message_id, payload.text))
        return cast(Any, FakeMessage(chat=FakeChat(chat_id), message_id=message_id))


@dataclass(slots=True)
class FakeNotifier:
    messages: list[tuple[int, str]]

    async def send_direct_message(self, *, telegram_user_id: int, text: str) -> Message:
        self.messages.append((telegram_user_id, text))
        return cast(
            Any,
            FakeMessage(chat=FakeChat(telegram_user_id), message_id=len(self.messages)),
        )


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
        group_publisher=FakeGroupPublisher(messages=[], edited_messages=[]),
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
        group_publisher=FakeGroupPublisher(messages=[], edited_messages=[]),
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
    group_publisher = FakeGroupPublisher(messages=[], edited_messages=[])
    processor = OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=group_publisher,
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
    assert any("Это еще не подтвержденное место" in text for _, text in notifier.messages)
    assert any("подтверждено 1 место" in text for _, text in notifier.messages)
    assert len(group_publisher.edited_messages) >= 4
    assert any("Свободно мест: 0" in text for _, _, text in group_publisher.edited_messages)

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


@pytest.mark.asyncio
async def test_worker_sends_announcement_update_and_cancellation_notifications(
    services: dict[str, object],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    (
        user_service,
        admin_access,
        event_service,
        _query_service,
        notification_service,
        publication_service,
        registration_service,
    ) = _services(services)
    admin_events = cast(AdminEventService, services["admin_events"])
    actor = await admin_access.load_actor(1000)
    timezone = load_timezone("Europe/Moscow")

    await user_service.ensure_user(
        TelegramProfile(
            telegram_user_id=3201,
            username="announce",
            first_name="Ann",
            last_name=None,
        )
    )
    await user_service.ensure_user(
        TelegramProfile(
            telegram_user_id=3202,
            username="guest",
            first_name="Guest",
            last_name=None,
        )
    )
    await notification_service.set_new_events_enabled(3201, True)

    start = datetime.now(tz=UTC) + timedelta(days=4)
    draft = EventDraft(
        tea_name="Габа Алишань",
        description="Уведомления",
        starts_at_local=start.astimezone(timezone),
        starts_at_utc=start,
        capacity=2,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=(start - timedelta(hours=4)).astimezone(timezone),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key="publish-notification-flow",
    )

    announcement_notifier = FakeNotifier(messages=[])
    await OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=cast(Any, FakeGroupPublisher(messages=[], edited_messages=[])),
        notifier=cast(Any, announcement_notifier),
        publication_renderer=TelegramPublicationRenderer(),
        bot_username="tea_party_bot",
        group_chat_id=-100123,
        timezone_name="Europe/Moscow",
        clock=SystemClock(),
        retry_delay_seconds=1,
    ).run_once(limit=10)

    assert requested.batch_id is not None
    assert announcement_notifier.messages == []

    flow_notifier = FakeNotifier(messages=[])
    flow_group_publisher = FakeGroupPublisher(messages=[], edited_messages=[])
    await OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=cast(Any, flow_group_publisher),
        notifier=cast(Any, flow_notifier),
        publication_renderer=TelegramPublicationRenderer(),
        bot_username="tea_party_bot",
        group_chat_id=-100123,
        timezone_name="Europe/Moscow",
        clock=SystemClock(),
        retry_delay_seconds=1,
    ).run_once(limit=10)

    assert flow_notifier.messages == [
        (
            3201,
            "Анонс новой дегустации.\n"
            "Габа Алишань\n"
            f"{start.astimezone(timezone):%d.%m.%Y %H:%M}\n"
            "Записаться: https://t.me/tea_party_bot?start=event-MQ",
        )
    ]
    assert flow_group_publisher.edited_messages == []

    await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=3202,
            username="guest",
            first_name="Guest",
            last_name=None,
        ),
        event_id=saved.event_ids[0],
        idempotency_key="flow-r1",
    )
    updated_start = start + timedelta(days=1)
    await admin_events.update_event_fields(
        actor=actor,
        event_id=saved.event_ids[0],
        tea_name="Габа Улун",
        starts_at=updated_start,
        cancel_deadline_at=updated_start - timedelta(hours=5),
    )
    await admin_events.cancel_event(actor=actor, event_id=saved.event_ids[0])

    state_notifier = FakeNotifier(messages=[])
    state_group_publisher = FakeGroupPublisher(messages=[], edited_messages=[])
    await OutboxProcessor(
        session_factory=session_factory,
        publication_service=publication_service,
        group_publisher=cast(Any, state_group_publisher),
        notifier=cast(Any, state_notifier),
        publication_renderer=TelegramPublicationRenderer(),
        bot_username="tea_party_bot",
        group_chat_id=-100123,
        timezone_name="Europe/Moscow",
        clock=SystemClock(),
        retry_delay_seconds=1,
    ).run_once(limit=20)

    assert any(
        user_id == 3202 and "Событие изменено." in text for user_id, text in state_notifier.messages
    )
    assert any("Название: Габа Алишань -> Габа Улун" in text for _, text in state_notifier.messages)
    assert any(
        user_id == 3202 and "Событие отменено." in text for user_id, text in state_notifier.messages
    )
    assert len(state_group_publisher.edited_messages) >= 3


@pytest.mark.asyncio
async def test_admin_sensitive_reads_are_audited(
    services: dict[str, object],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    (
        user_service,
        admin_access,
        event_service,
        query_service,
        _notification_service,
        publication_service,
        registration_service,
    ) = _services(services)
    timezone = load_timezone("Europe/Moscow")
    auth = DomainAuthorizationService()
    event_read_model = SqlAlchemyEventReadModelPort(
        session_factory=session_factory,
        timezone=timezone,
    )
    registration_port = SqlAlchemyRegistrationCommandPort(
        registration_service=registration_service,
        query_service=query_service,
        events=event_read_model,
    )
    user_sync = SqlAlchemyTelegramUserSyncPort(user_service)
    actor = await admin_access.load_actor(1000)

    app_service = TelegramBotApplicationService(
        roles=SqlAlchemyAdminRoleRepository(session_factory),
        authorization_service=auth,
        drafting_service=cast(Any, object()),
        admin_audit=AdminAuditService(
            cast(Any, cast("Any", lambda: cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))))
        ),
        user_sync=cast(Any, user_sync),
        events=event_read_model,
        registrations=cast(Any, registration_port),
        notifications=cast(Any, object()),
        publication=cast(Any, object()),
        admin_commands=cast(Any, object()),
        admin_role_management=cast(
            Any,
            SqlAlchemyAdminRoleManagementPort(
                AdminRoleManagementService(
                    cast(
                        Any,
                        cast(
                            "Any", lambda: cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))
                        ),
                    ),
                    auth,
                )
            ),
        ),
        system_settings_management=cast(
            Any,
            SqlAlchemySystemSettingsManagementPort(
                SystemSettingsService(
                    cast(
                        Any,
                        cast(
                            "Any", lambda: cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))
                        ),
                    ),
                    auth,
                )
            ),
        ),
    )

    start = datetime.now(tz=UTC) + timedelta(days=3)
    draft = EventDraft(
        tea_name="Bai Mu Dan",
        description="Проверка аудита",
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
        idempotency_key="publish-audit-read",
    )
    await publication_service.mark_publication_succeeded(
        batch_id=requested.batch_id or 0,
        event_ids=list(requested.event_ids),
        chat_id=-100123,
        message_id=777,
    )

    await user_sync.upsert_user(
        TelegramUserProfile(
            telegram_user_id=3101,
            username="reader1",
            first_name="Reader",
            last_name="One",
        )
    )
    await user_sync.upsert_user(
        TelegramUserProfile(
            telegram_user_id=3102,
            username="reader2",
            first_name="Reader",
            last_name="Two",
        )
    )
    await registration_port.register_for_event(
        telegram_user_id=3101,
        event_id=str(saved.event_ids[0]),
        idempotency_key="audit-read-r1",
    )
    await registration_port.register_for_event(
        telegram_user_id=3102,
        event_id=str(saved.event_ids[0]),
        idempotency_key="audit-read-r2",
    )

    events = await app_service.list_admin_events(actor)
    roster = await app_service.get_event_roster(actor=actor, event_id=str(saved.event_ids[0]))

    assert len(events) == 1
    assert roster is not None
    assert len(roster.participants) == 1
    assert len(roster.waitlist) == 1

    async with session_factory() as session:
        audit_rows = (
            (
                await session.execute(
                    select(AdminAuditLogModel)
                    .where(
                        AdminAuditLogModel.action.in_(
                            ["admin_events_listed", "event_roster_viewed"]
                        )
                    )
                    .order_by(AdminAuditLogModel.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert [row.action for row in audit_rows] == ["admin_events_listed", "event_roster_viewed"]
    assert audit_rows[0].target_id == "*"
    assert audit_rows[0].payload_json == {"event_count": 1}
    assert audit_rows[1].target_id == str(saved.event_ids[0])
    assert audit_rows[1].payload_json == {
        "found": True,
        "confirmed_count": 1,
        "waitlist_count": 1,
    }
