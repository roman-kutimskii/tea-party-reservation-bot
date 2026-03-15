from datetime import datetime

from tea_party_reservation_bot.application.telegram import PublicEventView
from tea_party_reservation_bot.domain.enums import CancelDeadlineSource
from tea_party_reservation_bot.domain.events import EventDraft, EventPreview
from tea_party_reservation_bot.infrastructure.telegram.deep_links import build_event_deep_link
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.time import load_timezone


def test_batch_publication_renders_hidden_links_without_buttons() -> None:
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

    first_link = build_event_deep_link(bot_username="tea_party_bot", event_id="event-1")
    second_link = build_event_deep_link(bot_username="tea_party_bot", event_id="event-2")
    assert payload.reply_markup is None
    assert f'<a href="{first_link}">Открыть регистрацию</a>' in payload.text
    assert f'<a href="{second_link}">Открыть регистрацию</a>' in payload.text


def test_single_publication_renders_hidden_link_without_button() -> None:
    renderer = TelegramPublicationRenderer()
    preview = EventPreview(
        normalized=EventDraft(
            tea_name="Очень длинное название чая " * 6,
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
    )

    payload = renderer.render_single_event_post(
        bot_username="tea_party_bot",
        preview=preview,
        event_id="event-1",
    )

    link = build_event_deep_link(bot_username="tea_party_bot", event_id="event-1")
    assert payload.reply_markup is None
    assert f'<a href="{link}">Открыть регистрацию</a>' in payload.text


def test_published_batch_publication_keeps_one_combined_post_with_distinct_links() -> None:
    renderer = TelegramPublicationRenderer()
    events = [
        PublicEventView(
            event_id="event-1",
            tea_name="Да Хун Пао",
            description="Первый вечер",
            starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
            cancel_deadline_at_local=datetime(
                2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
            ),
            capacity=12,
            reserved_seats=2,
        ),
        PublicEventView(
            event_id="event-2",
            tea_name="Те Гуань Инь",
            description="Второй вечер",
            starts_at_local=datetime(2099, 3, 23, 18, 30, tzinfo=load_timezone("Europe/Moscow")),
            cancel_deadline_at_local=datetime(
                2099, 3, 23, 14, 30, tzinfo=load_timezone("Europe/Moscow")
            ),
            capacity=10,
            reserved_seats=4,
        ),
    ]

    payload = renderer.render_published_batch_post(
        bot_username="tea_party_bot",
        events=events,
    )

    first_link = build_event_deep_link(bot_username="tea_party_bot", event_id="event-1")
    second_link = build_event_deep_link(bot_username="tea_party_bot", event_id="event-2")

    assert payload.reply_markup is None
    assert payload.text.count("Открыть регистрацию") == 2
    assert f'<a href="{first_link}">Открыть регистрацию</a>' in payload.text
    assert f'<a href="{second_link}">Открыть регистрацию</a>' in payload.text
    assert payload.text.count("\n\n") == 1
