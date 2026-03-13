from __future__ import annotations

from datetime import datetime

import pytest

from tea_party_reservation_bot.domain.enums import CancelDeadlineSource
from tea_party_reservation_bot.domain.events import EventInputBlock
from tea_party_reservation_bot.exceptions import DomainError
from tea_party_reservation_bot.time import load_timezone


def test_event_input_block_rejects_non_positive_capacity() -> None:
    with pytest.raises(DomainError, match='Поле "Мест": только целое число больше 0'):
        EventInputBlock(
            tea_name="Да Хун Пао",
            starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
            capacity=0,
            cancel_deadline_at_local=datetime(
                2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
            ),
            cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        )


def test_event_input_block_rejects_late_cancel_deadline() -> None:
    with pytest.raises(DomainError, match='Поле "Отмена до": должно быть раньше начала события'):
        EventInputBlock(
            tea_name="Да Хун Пао",
            starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
            capacity=12,
            cancel_deadline_at_local=datetime(
                2099, 3, 21, 19, 1, tzinfo=load_timezone("Europe/Moscow")
            ),
            cancel_deadline_source=CancelDeadlineSource.OVERRIDE,
        )
