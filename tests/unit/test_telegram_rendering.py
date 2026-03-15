from datetime import datetime

from tea_party_reservation_bot.application.telegram import (
    AdminEventView,
    AdminRoleAssignmentView,
    EventRosterView,
    ManagedSystemSettingsView,
    ParticipantView,
    PublicEventView,
)
from tea_party_reservation_bot.presentation.telegram.keyboards import (
    admin_menu_keyboard,
    draft_preview_keyboard,
    event_actions_keyboard,
    visitor_menu_keyboard,
)
from tea_party_reservation_bot.presentation.telegram.renderers import (
    render_admin_roles,
    render_event_card,
    render_roster,
    render_system_settings,
)
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


def test_menu_keyboards_return_distinct_instances() -> None:
    visitor_first = visitor_menu_keyboard()
    visitor_second = visitor_menu_keyboard()
    admin_first = admin_menu_keyboard(owner_controls=True)
    admin_second = admin_menu_keyboard(owner_controls=True)
    draft_first = draft_preview_keyboard()
    draft_second = draft_preview_keyboard()

    assert visitor_first is not visitor_second
    assert admin_first is not admin_second
    assert draft_first is not draft_second


def test_render_roster_uses_multiline_lists() -> None:
    roster = EventRosterView(
        event=AdminEventView(
            event_id="1",
            tea_name="Шу Пуэр",
            starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
            capacity=8,
            reserved_seats=2,
            status="published_open",
        ),
        participants=[
            ParticipantView(display_name="Alice", telegram_user_id=1001, status="confirmed"),
            ParticipantView(display_name="Bob", telegram_user_id=1002, status="confirmed"),
        ],
        waitlist=[ParticipantView(display_name="Charlie", telegram_user_id=1003, status="active")],
    )

    text = render_roster(roster)

    assert "Подтверждены:\n- Alice (1001)\n- Bob (1002)" in text
    assert "Лист ожидания:\n- Charlie (1003)" in text


def test_owner_menu_exposes_role_and_settings_buttons() -> None:
    keyboard = admin_menu_keyboard(owner_controls=True)

    assert keyboard.keyboard[-1][0].text == "Роли админов"
    assert keyboard.keyboard[-1][1].text == "Настройки системы"


def test_render_owner_management_views() -> None:
    roles = render_admin_roles(
        [AdminRoleAssignmentView(telegram_user_id=1000, display_name="@owner", roles=["owner"])]
    )
    settings = render_system_settings(
        ManagedSystemSettingsView(default_cancel_deadline_offset_minutes=180)
    )

    assert "@owner" in roles
    assert "/grant_role" in roles
    assert "180" in settings
    assert "/set_default_deadline" in settings
