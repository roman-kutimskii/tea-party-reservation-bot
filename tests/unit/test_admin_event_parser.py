from __future__ import annotations

from datetime import datetime

import pytest

from tea_party_reservation_bot.domain.enums import CancelDeadlineSource, EventStatus
from tea_party_reservation_bot.domain.parsing import AdminEventInputParser, BatchValidationError
from tea_party_reservation_bot.time import load_timezone


def test_parser_normalizes_single_event_with_default_deadline() -> None:
    parser = AdminEventInputParser(default_cancel_deadline_offset_minutes=240)

    result = parser.parse_one(
        """Чай: Да Хун Пао
Дата: 21.03.2099
Время: 19:00
Мест: 12
Описание: Весенний открытый вечер
""",
        timezone_name="Europe/Moscow",
    )

    assert result.tea_name == "Да Хун Пао"
    assert result.capacity == 12
    assert result.cancel_deadline_source is CancelDeadlineSource.DEFAULT
    assert result.cancel_deadline_at_local == datetime(
        2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
    )
    assert result.starts_at_utc.isoformat() == "2099-03-21T16:00:00+00:00"
    assert result.status is EventStatus.DRAFT


def test_parser_preserves_explicit_cancel_deadline() -> None:
    parser = AdminEventInputParser(default_cancel_deadline_offset_minutes=240)

    result = parser.parse_one(
        """Чай: Те Гуань Инь
Дата: 23.03.2099
Время: 18:30
Мест: 10
Отмена до: 23.03.2099 12:00
""",
        timezone_name="Europe/Moscow",
    )

    assert result.cancel_deadline_source is CancelDeadlineSource.OVERRIDE
    assert result.cancel_deadline_at_local == datetime(
        2099, 3, 23, 12, 0, tzinfo=load_timezone("Europe/Moscow")
    )


def test_batch_parser_returns_block_specific_errors() -> None:
    parser = AdminEventInputParser(default_cancel_deadline_offset_minutes=240)

    with pytest.raises(BatchValidationError) as exc_info:
        parser.parse_many(
            """Чай: Да Хун Пао
Дата: 21.03.2099
Время: 19:00
Мест: 12
---
Чай: Те Гуань Инь
Дата: 23.03.2099
Время: 18:30
Мест: 0
""",
            timezone_name="Europe/Moscow",
        )

    assert (
        exc_info.value.errors[0].to_user_string()
        == 'Блок 2: Поле "Мест": только целое число больше 0'
    )


def test_parser_rejects_non_future_event() -> None:
    parser = AdminEventInputParser(default_cancel_deadline_offset_minutes=240)

    with pytest.raises(BatchValidationError) as exc_info:
        parser.parse_one(
            """Чай: Да Хун Пао
Дата: 01.01.2020
Время: 19:00
Мест: 12
""",
            timezone_name="Europe/Moscow",
        )

    assert exc_info.value.errors[0].to_user_string() == 'Поле "Дата": событие должно быть в будущем'
