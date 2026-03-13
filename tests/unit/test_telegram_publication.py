from datetime import datetime

from tea_party_reservation_bot.domain.enums import CancelDeadlineSource
from tea_party_reservation_bot.domain.events import EventDraft, EventPreview
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.time import load_timezone


def test_batch_publication_renders_distinct_buttons() -> None:
    renderer = TelegramPublicationRenderer()
    previews = [
        EventPreview(
            normalized=EventDraft(
                tea_name="Да Хун Пао",
                description="Первый вечер",
                starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
                starts_at_utc=datetime(2099, 3, 21, 16, 0, tzinfo=load_timezone("UTC")),
                capacity=12,
                cancel_deadline_source=CancelDeadlineSource.DEFAULT,
                cancel_deadline_at_local=datetime(
                    2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
                ),
                cancel_deadline_at_utc=datetime(2099, 3, 21, 12, 0, tzinfo=load_timezone("UTC")),
            ),
            block_number=1,
        ),
        EventPreview(
            normalized=EventDraft(
                tea_name="Те Гуань Инь",
                description="Второй вечер",
                starts_at_local=datetime(
                    2099, 3, 23, 18, 30, tzinfo=load_timezone("Europe/Moscow")
                ),
                starts_at_utc=datetime(2099, 3, 23, 15, 30, tzinfo=load_timezone("UTC")),
                capacity=10,
                cancel_deadline_source=CancelDeadlineSource.DEFAULT,
                cancel_deadline_at_local=datetime(
                    2099, 3, 23, 14, 30, tzinfo=load_timezone("Europe/Moscow")
                ),
                cancel_deadline_at_utc=datetime(2099, 3, 23, 11, 30, tzinfo=load_timezone("UTC")),
            ),
            block_number=2,
        ),
    ]

    payload = renderer.render_batch_post(
        bot_username="tea_party_bot",
        previews=previews,
        event_ids=["event-1", "event-2"],
    )

    assert len(payload.reply_markup.inline_keyboard) == 2
    assert (
        payload.reply_markup.inline_keyboard[0][0].url
        != payload.reply_markup.inline_keyboard[1][0].url
    )
