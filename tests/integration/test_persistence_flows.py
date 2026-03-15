from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.application.dto import TelegramProfile
from tea_party_reservation_bot.application.services import (
    AdminAccessService,
    AdminEventService,
    AdminRoleManagementService,
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationResult,
    RegistrationService,
    SystemSettingsService,
    UserApplicationService,
)
from tea_party_reservation_bot.domain.enums import AdminRole, CancelDeadlineSource, EventStatus
from tea_party_reservation_bot.domain.events import EventDraft
from tea_party_reservation_bot.exceptions import ConflictError
from tea_party_reservation_bot.infrastructure.db.models import (
    EventOccurrenceModel,
    OutboxEventModel,
    ProcessedCommandModel,
    ReservationModel,
    WaitlistEntryModel,
)


async def _create_published_event(
    services: dict[str, object],
    *,
    capacity: int,
    starts_at: datetime | None = None,
) -> int:
    admin_access = cast(AdminAccessService, services["admin_access"])
    event_service = cast(EventPersistenceService, services["events"])
    publication_service = cast(PublicationService, services["publication"])

    actor = await admin_access.load_actor(1000)
    start = starts_at or datetime.now(tz=UTC) + timedelta(days=3)
    draft = EventDraft(
        tea_name="Да Хун Пао",
        description="Вечерняя дегустация",
        starts_at_local=start,
        starts_at_utc=start,
        capacity=capacity,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=start - timedelta(hours=4),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key=f"publish-{saved.event_ids[0]}",
    )
    await publication_service.mark_publication_succeeded(
        batch_id=requested.batch_id or 0,
        event_ids=list(requested.event_ids),
        chat_id=-100123,
        message_id=999,
    )
    return saved.event_ids[0]


@pytest.mark.asyncio
async def test_publication_success_transitions_draft_event_to_published_open(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=2)

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, event_id)
        assert event is not None
        assert event.status == EventStatus.PUBLISHED_OPEN
        assert event.published_at is not None


@pytest.mark.asyncio
async def test_publication_failure_resets_event_to_draft(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_access = cast(AdminAccessService, services["admin_access"])
    event_service = cast(EventPersistenceService, services["events"])
    publication_service = cast(PublicationService, services["publication"])

    actor = await admin_access.load_actor(1000)
    start = datetime.now(tz=UTC) + timedelta(days=3)
    draft = EventDraft(
        tea_name="Те Гуань Инь",
        description="Неудачная публикация",
        starts_at_local=start,
        starts_at_utc=start,
        capacity=4,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=start - timedelta(hours=4),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key=f"publish-fail-{saved.event_ids[0]}",
    )

    await publication_service.mark_publication_failed(
        batch_id=requested.batch_id or 0,
        event_ids=list(requested.event_ids),
    )

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, saved.event_ids[0])
        assert event is not None
        assert event.status == EventStatus.DRAFT
        assert event.publication_batch_id is None
        assert event.published_at is None


@pytest.mark.asyncio
async def test_registration_is_idempotent(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=1)
    registration_service = cast(RegistrationService, services["registration"])
    profile = TelegramProfile(
        telegram_user_id=2001, username="guest", first_name="Guest", last_name=None
    )

    first = await registration_service.register(
        profile=profile,
        event_id=event_id,
        idempotency_key="reg-1",
    )
    second = await registration_service.register(
        profile=profile,
        event_id=event_id,
        idempotency_key="reg-1",
    )

    assert first == second
    assert first.outcome == "confirmed"

    async with session_factory() as session:
        reservation_count = await session.scalar(select(func.count()).select_from(ReservationModel))
        processed_count = await session.scalar(
            select(func.count()).select_from(ProcessedCommandModel)
        )
        assert reservation_count == 1
        assert processed_count == 2


@pytest.mark.asyncio
async def test_cancellation_promotes_waitlist_entry(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=1)
    registration_service = cast(RegistrationService, services["registration"])
    query_service = cast(EventQueryService, services["query"])

    await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=3001, username="u1", first_name="One", last_name=None
        ),
        event_id=event_id,
        idempotency_key="reg-a",
    )
    waitlisted = await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=3002, username="u2", first_name="Two", last_name=None
        ),
        event_id=event_id,
        idempotency_key="reg-b",
    )

    assert waitlisted.outcome == "waitlisted"

    cancelled = await registration_service.cancel(
        telegram_user_id=3001,
        event_id=event_id,
        idempotency_key="cancel-a",
    )
    registrations = await query_service.list_user_active_registrations(3002)

    assert cancelled.promoted_user_id is not None
    assert len(registrations) == 1
    assert registrations[0].event_id == event_id

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, event_id)
        waitlist_statuses = (
            (await session.execute(select(WaitlistEntryModel.status))).scalars().all()
        )
        outbox_types = (await session.execute(select(OutboxEventModel.event_type))).scalars().all()
        assert event is not None
        assert event.reserved_seats == 1
        assert event.status == EventStatus.PUBLISHED_FULL
        assert waitlist_statuses == ["promoted"]
        assert "waitlist.promoted" in outbox_types


@pytest.mark.asyncio
async def test_parallel_last_seat_allocation_results_in_one_confirmed_and_one_waitlisted(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=1)
    registration_service = cast(RegistrationService, services["registration"])

    async def register(profile: TelegramProfile, key: str) -> RegistrationResult:
        return await registration_service.register(
            profile=profile, event_id=event_id, idempotency_key=key
        )

    results = await asyncio.gather(
        register(
            TelegramProfile(telegram_user_id=4001, username="u1", first_name="One", last_name=None),
            "k1",
        ),
        register(
            TelegramProfile(telegram_user_id=4002, username="u2", first_name="Two", last_name=None),
            "k2",
        ),
    )

    outcomes = sorted(result.outcome for result in results)
    assert outcomes == ["confirmed", "waitlisted"]

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, event_id)
        confirmed = await session.scalar(
            select(func.count())
            .select_from(ReservationModel)
            .where(ReservationModel.status == "confirmed")
        )
        waitlisted = await session.scalar(
            select(func.count())
            .select_from(WaitlistEntryModel)
            .where(WaitlistEntryModel.status == "active")
        )
        assert event is not None
        assert event.reserved_seats == 1
        assert confirmed == 1
        assert waitlisted == 1


@pytest.mark.asyncio
async def test_notification_preferences_and_admin_roles(
    services: dict[str, object],
) -> None:
    user_service = cast(UserApplicationService, services["user"])
    admin_access = cast(AdminAccessService, services["admin_access"])
    notification_service = cast(NotificationPreferenceService, services["notifications"])

    await user_service.ensure_user(
        TelegramProfile(telegram_user_id=5001, username=None, first_name="User", last_name=None)
    )
    prefs = await notification_service.set_new_events_enabled(5001, True)
    actor = await admin_access.load_actor(1000)

    assert prefs.new_events_enabled is True
    assert "owner" in {role.value for role in actor.roles.roles}


@pytest.mark.asyncio
async def test_publication_success_enqueues_new_tasting_announcements_for_subscribers(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_service = cast(UserApplicationService, services["user"])
    notification_service = cast(NotificationPreferenceService, services["notifications"])
    admin_access = cast(AdminAccessService, services["admin_access"])
    event_service = cast(EventPersistenceService, services["events"])
    publication_service = cast(PublicationService, services["publication"])

    await user_service.ensure_user(
        TelegramProfile(telegram_user_id=5101, username="sub1", first_name="Sub", last_name=None)
    )
    await user_service.ensure_user(
        TelegramProfile(telegram_user_id=5102, username="sub2", first_name="Muted", last_name=None)
    )
    await notification_service.set_new_events_enabled(5101, True)
    await notification_service.set_new_events_enabled(5102, False)

    actor = await admin_access.load_actor(1000)
    start = datetime.now(tz=UTC) + timedelta(days=4)
    draft = EventDraft(
        tea_name="Лун Цзин",
        description="Новый анонс",
        starts_at_local=start,
        starts_at_utc=start,
        capacity=6,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=start - timedelta(hours=4),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key="publish-announcement",
    )

    await publication_service.mark_publication_succeeded(
        batch_id=requested.batch_id or 0,
        event_ids=list(requested.event_ids),
        chat_id=-100123,
        message_id=1001,
    )

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEventModel).where(OutboxEventModel.event_type == "event.announced")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].payload_json["event_id"] == saved.event_ids[0]
    assert rows[0].payload_json["telegram_user_id"] == 5101


@pytest.mark.asyncio
async def test_duplicate_registration_with_new_idempotency_key_is_rejected(
    services: dict[str, object],
) -> None:
    event_id = await _create_published_event(services, capacity=2)
    registration_service = cast(RegistrationService, services["registration"])
    profile = TelegramProfile(
        telegram_user_id=6001, username="repeat", first_name="Repeat", last_name=None
    )

    await registration_service.register(profile=profile, event_id=event_id, idempotency_key="first")
    with pytest.raises(ConflictError, match="активная запись"):
        await registration_service.register(
            profile=profile, event_id=event_id, idempotency_key="second"
        )


@pytest.mark.asyncio
async def test_admin_can_edit_capacity_and_close_then_reopen_registration(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=1)
    admin_access = cast(AdminAccessService, services["admin_access"])
    admin_events = cast(AdminEventService, services["admin_events"])
    registration_service = cast(RegistrationService, services["registration"])
    actor = await admin_access.load_actor(1000)

    await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=7001, username="u1", first_name="One", last_name=None
        ),
        event_id=event_id,
        idempotency_key="admin-capacity-r1",
    )
    await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=7002, username="u2", first_name="Two", last_name=None
        ),
        event_id=event_id,
        idempotency_key="admin-capacity-r2",
    )

    await admin_events.set_capacity(actor=actor, event_id=event_id, capacity=2)
    await admin_events.close_registration(actor=actor, event_id=event_id)
    await admin_events.reopen_registration(actor=actor, event_id=event_id)

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, event_id)
        reservations = (
            (
                await session.execute(
                    select(ReservationModel).where(ReservationModel.status == "confirmed")
                )
            )
            .scalars()
            .all()
        )
        waitlist = (
            (
                await session.execute(
                    select(WaitlistEntryModel).where(WaitlistEntryModel.status == "promoted")
                )
            )
            .scalars()
            .all()
        )
        assert event is not None
        assert event.capacity == 2
        assert event.reserved_seats == 2
        assert event.status == EventStatus.PUBLISHED_FULL
        assert len(reservations) == 2
        assert len(waitlist) == 1


@pytest.mark.asyncio
async def test_admin_event_updates_enqueue_detailed_change_notifications(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=2)
    admin_access = cast(AdminAccessService, services["admin_access"])
    admin_events = cast(AdminEventService, services["admin_events"])
    registration_service = cast(RegistrationService, services["registration"])
    actor = await admin_access.load_actor(1000)

    await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=7101, username="guest1", first_name="Guest", last_name=None
        ),
        event_id=event_id,
        idempotency_key="event-update-r1",
    )

    new_start = datetime.now(tz=UTC) + timedelta(days=5)
    await admin_events.update_event_fields(
        actor=actor,
        event_id=event_id,
        tea_name="Шэн Пуэр",
        starts_at=new_start,
        cancel_deadline_at=new_start - timedelta(hours=6),
    )

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEventModel)
                    .where(OutboxEventModel.event_type == "event.updated")
                    .order_by(OutboxEventModel.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert rows
    assert rows[-1].payload_json["telegram_user_id"] == 7101
    assert "Изменения:" in rows[-1].payload_json["details"]
    assert "Название: Да Хун Пао -> Шэн Пуэр" in rows[-1].payload_json["details"]
    assert "Отмена до:" in rows[-1].payload_json["details"]


@pytest.mark.asyncio
async def test_admin_can_manage_participants_and_cancel_event(
    services: dict[str, object], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _create_published_event(services, capacity=2)
    admin_access = cast(AdminAccessService, services["admin_access"])
    admin_events = cast(AdminEventService, services["admin_events"])
    user_service = cast(UserApplicationService, services["user"])
    actor = await admin_access.load_actor(1000)

    for telegram_user_id, username, first_name in [
        (8001, "alpha", "Alpha"),
        (8002, "beta", "Beta"),
        (8003, "gamma", "Gamma"),
    ]:
        await user_service.ensure_user(
            TelegramProfile(
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=None,
            )
        )

    await admin_events.add_participant(
        actor=actor,
        event_id=event_id,
        telegram_user_id=8001,
        target="confirmed",
    )
    await admin_events.add_participant(
        actor=actor,
        event_id=event_id,
        telegram_user_id=8002,
        target="waitlist",
    )
    await admin_events.move_participant(
        actor=actor,
        event_id=event_id,
        telegram_user_id=8002,
        target="confirmed",
    )
    await admin_events.move_participant(
        actor=actor,
        event_id=event_id,
        telegram_user_id=8001,
        target="waitlist",
    )
    await admin_events.remove_participant(
        actor=actor,
        event_id=event_id,
        telegram_user_id=8001,
    )
    await admin_events.add_participant(
        actor=actor,
        event_id=event_id,
        telegram_user_id=8003,
        target="confirmed",
    )
    await admin_events.cancel_event(actor=actor, event_id=event_id)

    async with session_factory() as session:
        event = await session.get(EventOccurrenceModel, event_id)
        confirmed = (
            (
                await session.execute(
                    select(ReservationModel.status).order_by(ReservationModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
        waitlist_statuses = (
            (
                await session.execute(
                    select(WaitlistEntryModel.status).order_by(WaitlistEntryModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
        outbox_types = (await session.execute(select(OutboxEventModel.event_type))).scalars().all()
        assert event is not None
        assert event.status == EventStatus.CANCELLED
        assert event.reserved_seats == 0
        assert confirmed == ["cancelled", "cancelled", "cancelled"]
        assert waitlist_statuses == ["promoted", "cancelled"]
        assert "waitlist.joined" in outbox_types
        assert "waitlist.promoted" in outbox_types
        assert "waitlist.cancelled" in outbox_types
        assert "event.cancelled" in outbox_types


@pytest.mark.asyncio
async def test_owner_can_manage_admin_roles_and_system_settings(
    services: dict[str, object],
) -> None:
    user_service = cast(UserApplicationService, services["user"])
    admin_access = cast(AdminAccessService, services["admin_access"])
    admin_roles = cast(AdminRoleManagementService, services["admin_roles"])
    system_settings = cast(SystemSettingsService, services["system_settings"])

    await user_service.ensure_user(
        TelegramProfile(
            telegram_user_id=9001, username="manager1", first_name="Manager", last_name=None
        )
    )
    actor = await admin_access.load_actor(1000)

    assigned = await admin_roles.assign_role(
        actor=actor, telegram_user_id=9001, role=AdminRole.MANAGER
    )
    settings = await system_settings.set_default_cancel_deadline_offset_minutes(
        actor=actor, minutes=180
    )
    assignments = await admin_roles.list_assignments(actor)

    assert "manager" in assigned
    assert settings.default_cancel_deadline_offset_minutes == 180
    assert any(
        item.telegram_user_id == 9001 and AdminRole.MANAGER in item.roles for item in assignments
    )
