from datetime import datetime

from tea_party_reservation_bot.application.telegram import PublicEventView
from tea_party_reservation_bot.presentation.telegram.keyboards import event_actions_keyboard
from tea_party_reservation_bot.presentation.telegram.renderers import render_event_card
from tea_party_reservation_bot.time import load_timezone


def test_event_card_mentions_waitlist_when_full() -> None:
    event = PublicEventView(
        event_id="full-1",
        tea_name="Шу Пуэр",
        starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
        cancel_deadline_at_local=datetime(
            2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
        ),
        capacity=8,
        reserved_seats=8,
    )

    text = render_event_card(event)
    keyboard = event_actions_keyboard(event)

    assert "Мест нет" in text
    assert keyboard.inline_keyboard[0][0].text == "На лист ожидания"
