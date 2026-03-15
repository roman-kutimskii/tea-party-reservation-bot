from datetime import UTC, datetime, timedelta

from tea_party_reservation_bot.domain.enums import EventStatus
from tea_party_reservation_bot.infrastructure.db.models import EventOccurrenceModel


def _build_event(
    *, status: EventStatus, capacity: int = 4, reserved_seats: int = 0
) -> EventOccurrenceModel:
    start = datetime.now(tz=UTC) + timedelta(days=1)
    return EventOccurrenceModel(
        tea_name="Да Хун Пао",
        description="Тестовая дегустация",
        starts_at=start,
        timezone="Europe/Moscow",
        capacity=capacity,
        reserved_seats=reserved_seats,
        cancel_deadline_at=start - timedelta(hours=2),
        cancel_deadline_source="default",
        status=status,
        created_by_user_id=1,
    )


def test_close_registration_sets_explicit_closed_state() -> None:
    event = _build_event(status=EventStatus.PUBLISHED_OPEN, reserved_seats=1)

    event.close_registration()

    assert event.status == EventStatus.REGISTRATION_CLOSED


def test_reopen_registration_restores_capacity_based_state() -> None:
    full_event = _build_event(
        status=EventStatus.REGISTRATION_CLOSED,
        capacity=2,
        reserved_seats=2,
    )
    open_event = _build_event(
        status=EventStatus.REGISTRATION_CLOSED,
        capacity=3,
        reserved_seats=1,
    )

    full_event.reopen_registration()
    open_event.reopen_registration()

    assert full_event.status == EventStatus.PUBLISHED_FULL
    assert open_event.status == EventStatus.PUBLISHED_OPEN


def test_cancel_and_complete_are_terminal_transitions() -> None:
    cancelled_event = _build_event(status=EventStatus.PUBLISHED_FULL, capacity=2, reserved_seats=2)
    completed_event = _build_event(status=EventStatus.PUBLISHED_OPEN, reserved_seats=1)

    cancelled_event.cancel()
    completed_event.complete()
    cancelled_event.sync_status_from_capacity()
    completed_event.sync_status_from_capacity()

    assert cancelled_event.status == EventStatus.CANCELLED
    assert completed_event.status == EventStatus.COMPLETED
