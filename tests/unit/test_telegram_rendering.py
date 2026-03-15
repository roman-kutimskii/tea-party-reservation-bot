from datetime import datetime

from tea_party_reservation_bot.application.telegram import (
    AdminEventView,
    AdminRoleAssignmentView,
    EventRosterView,
    ManagedSystemSettingsView,
    ParticipantView,
    PublicEventView,
    RegistrationResult,
    UserRegistrationView,
)
from tea_party_reservation_bot.domain.enums import CancelDeadlineSource
from tea_party_reservation_bot.domain.events import EventDraft, EventPreview
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramDeepLinkPreview,
    TelegramGroupPostPayload,
)
from tea_party_reservation_bot.presentation.telegram.keyboards import (
    admin_menu_keyboard,
    draft_preview_keyboard,
    event_actions_keyboard,
    roster_actions_keyboard,
    visitor_menu_keyboard,
)
from tea_party_reservation_bot.presentation.telegram.renderers import (
    render_admin_preview,
    render_admin_roles,
    render_event_card,
    render_my_registration,
    render_registration_result,
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
            cancel_deadline_at_local=datetime(
                2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
            ),
            cancel_deadline_passed=True,
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

    assert "Отмена до: 21.03.2099 15:00" in text
    assert "Доступна админ-отмена" in text
    assert "Подтверждены:\n- Alice (1001)\n- Bob (1002)" in text
    assert "Лист ожидания:\n- Charlie (1003)" in text


def test_roster_keyboard_exposes_operational_cancel_buttons() -> None:
    timezone = load_timezone("Europe/Moscow")
    roster = EventRosterView(
        event=AdminEventView(
            event_id="7",
            tea_name="Шу Пуэр",
            starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=timezone),
            cancel_deadline_at_local=datetime(2099, 3, 21, 15, 0, tzinfo=timezone),
            cancel_deadline_passed=True,
            capacity=8,
            reserved_seats=1,
            status="published_open",
        ),
        participants=[
            ParticipantView(display_name="Alice", telegram_user_id=1001, status="confirmed")
        ],
        waitlist=[],
    )

    keyboard = roster_actions_keyboard(roster)

    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == "Поздняя отмена 1001"
    assert keyboard.inline_keyboard[0][0].callback_data == "admin:cancel_override:7:1001"


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
    assert "Срок отмены по умолчанию" in settings


def test_render_registration_result_mentions_single_confirmed_seat() -> None:
    event = PublicEventView(
        event_id="event-1",
        tea_name="Шу Пуэр",
        starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
        cancel_deadline_at_local=datetime(
            2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
        ),
        capacity=8,
        reserved_seats=3,
    )

    text = render_registration_result(RegistrationResult(event=event, status="confirmed"))

    assert "За вами подтверждено 1 место" in text
    assert "Мест: 1" in text


def test_render_waitlist_result_clarifies_seat_is_not_confirmed() -> None:
    event = PublicEventView(
        event_id="event-2",
        tea_name="Да Хун Пао",
        starts_at_local=datetime(2099, 3, 22, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
        cancel_deadline_at_local=datetime(
            2099, 3, 22, 15, 0, tzinfo=load_timezone("Europe/Moscow")
        ),
        capacity=8,
        reserved_seats=8,
    )

    text = render_registration_result(RegistrationResult(event=event, status="waitlist"))

    assert "Это еще не подтвержденное место" in text
    assert "Выйти из листа ожидания можно в любой момент" in text
    assert "Отмена до:" not in text


def test_render_my_registration_mentions_single_confirmed_seat() -> None:
    registration = UserRegistrationView(
        registration_id="reg-1",
        event_id="event-1",
        tea_name="Шу Пуэр",
        starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
        cancel_deadline_at_local=datetime(
            2099, 3, 21, 15, 0, tzinfo=load_timezone("Europe/Moscow")
        ),
        status="confirmed",
        can_cancel=True,
    )

    text = render_my_registration(registration)

    assert "Подтверждено 1 место" in text


def test_render_my_waitlist_registration_mentions_self_cancellation_rule() -> None:
    registration = UserRegistrationView(
        registration_id="reg-2",
        event_id="event-2",
        tea_name="Да Хун Пао",
        starts_at_local=datetime(2099, 3, 22, 19, 0, tzinfo=load_timezone("Europe/Moscow")),
        cancel_deadline_at_local=datetime(
            2099, 3, 22, 15, 0, tzinfo=load_timezone("Europe/Moscow")
        ),
        status="waitlist",
        can_cancel=True,
        waitlist_position=2,
    )

    text = render_my_registration(registration)

    assert "Лист ожидания" in text
    assert "Выйти из листа ожидания можно в любой момент" in text
    assert "Позиция: 2" in text


def test_render_admin_preview_shows_final_post_text_and_link_mapping() -> None:
    timezone = load_timezone("Europe/Moscow")
    preview = EventPreview(
        normalized=EventDraft(
            tea_name="Да Хун Пао",
            description="Вечер утесных улунов",
            starts_at_local=datetime(2099, 3, 21, 19, 0, tzinfo=timezone),
            starts_at_utc=datetime(2099, 3, 21, 16, 0, tzinfo=load_timezone("UTC")),
            capacity=12,
            cancel_deadline_source=CancelDeadlineSource.DEFAULT,
            cancel_deadline_at_local=datetime(2099, 3, 21, 15, 0, tzinfo=timezone),
            cancel_deadline_at_utc=datetime(2099, 3, 21, 12, 0, tzinfo=load_timezone("UTC")),
        ),
        block_number=1,
    )

    text = render_admin_preview(
        [preview],
        TelegramGroupPostPayload(
            text=(
                'Да Хун Пао\n<a href="https://t.me/tea_party_bot?start=test">'
                "Открыть регистрацию</a>"
            ),
            preview_text="Да Хун Пао\nОткрыть регистрацию",
            deep_links=(
                TelegramDeepLinkPreview(
                    label="1. Да Хун Пао",
                    url="https://t.me/tea_party_bot?start=test",
                ),
            ),
        ),
    )

    assert "Итоговый пост в группу" in text
    assert "<pre>Да Хун Пао\nОткрыть регистрацию</pre>" in text
    assert "Сопоставление ссылок записи" in text
    assert "1. Да Хун Пао: https://t.me/tea_party_bot?start=test" in text
