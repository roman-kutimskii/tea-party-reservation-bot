from __future__ import annotations

from collections.abc import Sequence
from html import escape

from tea_party_reservation_bot.application.telegram import (
    AdminEventView,
    EventRosterView,
    NotificationSettingsView,
    PublicEventView,
    RegistrationResult,
    UserRegistrationView,
)
from tea_party_reservation_bot.domain.events import EventPreview
from tea_party_reservation_bot.infrastructure.telegram.publication import TelegramGroupPostPayload


def render_welcome() -> str:
    return "Здравствуйте. Выберите действие ниже."


def render_help() -> str:
    return (
        "Команды: /start, /events, /my, /help, /cancel.\n"
        "Для записи откройте событие и нажмите кнопку."
    )


def render_unknown_text() -> str:
    return "Не понял сообщение. Пожалуйста, используйте кнопки ниже или /start."


def render_event_card(event: PublicEventView) -> str:
    seats = "Мест нет" if event.is_full else f"Свободно мест: {event.seats_left}"
    lines = [
        escape(event.tea_name),
        f"Когда: {event.starts_at_local:%d.%m.%Y %H:%M}",
        seats,
        f"Отмена до: {event.cancel_deadline_at_local:%d.%m %H:%M}",
    ]
    if event.description:
        lines.append(escape(event.description))
    return "\n".join(lines)


def render_event_details(event: PublicEventView) -> str:
    lines = [render_event_card(event), f"Статус: {event.status}"]
    return "\n".join(lines)


def render_events_empty() -> str:
    return "Пока нет опубликованных дегустаций."


def render_registration_result(result: RegistrationResult) -> str:
    headline = "Вы записаны." if result.status == "confirmed" else "Вы в листе ожидания."
    return (
        f"{headline}\n"
        f"{escape(result.event.tea_name)}\n"
        f"{result.event.starts_at_local:%d.%m.%Y %H:%M}\n"
        f"Отмена до: {result.event.cancel_deadline_at_local:%d.%m %H:%M}"
    )


def render_my_empty() -> str:
    return "У Вас пока нет активных записей."


def render_my_registration(registration: UserRegistrationView) -> str:
    status = "Запись подтверждена" if registration.status == "confirmed" else "Лист ожидания"
    lines = [
        escape(registration.tea_name),
        f"Когда: {registration.starts_at_local:%d.%m.%Y %H:%M}",
        status,
    ]
    if registration.status == "confirmed":
        lines.append(f"Отмена до: {registration.cancel_deadline_at_local:%d.%m %H:%M}")
    if registration.waitlist_position is not None:
        lines.append(f"Позиция: {registration.waitlist_position}")
    return "\n".join(lines)


def render_notifications(settings: NotificationSettingsView) -> str:
    state = "включены" if settings.enabled else "выключены"
    return f"Уведомления о новых дегустациях {state}."


def render_admin_denied() -> str:
    return "У Вас нет доступа к разделу администратора."


def render_single_event_template() -> str:
    return (
        "Отправьте один блок:\n"
        "Чай: &lt;название&gt;\n"
        "Дата: &lt;ДД.ММ.ГГГГ&gt;\n"
        "Время: &lt;ЧЧ:ММ&gt;\n"
        "Мест: &lt;число&gt;\n"
        "Отмена до: &lt;ДД.ММ.ГГГГ ЧЧ:ММ&gt;\n"
        "Описание: &lt;текст&gt;"
    )


def render_batch_template() -> str:
    return f"{render_single_event_template()}\n---\nСледующий блок события"


def render_admin_preview(
    previews: Sequence[EventPreview],
    publication_preview: TelegramGroupPostPayload,
) -> str:
    parts = ["Предпросмотр:"]
    for index, preview in enumerate(previews, start=1):
        event = preview.normalized
        parts.append(
            "\n".join(
                [
                    f"Блок {index}: {escape(event.tea_name)}",
                    f"Старт: {event.starts_at_local:%d.%m.%Y %H:%M}",
                    f"Мест: {event.capacity}",
                    f"Отмена до: {event.cancel_deadline_at_local:%d.%m.%Y %H:%M}",
                ]
            )
        )
    parts.append(f"Пост в группу:\n{publication_preview.text}")
    return "\n\n".join(parts)


def render_admin_events(events: Sequence[AdminEventView]) -> str:
    if not events:
        return "Событий пока нет."
    return "Выберите событие для просмотра списка участников."


def render_roster(roster: EventRosterView) -> str:
    confirmed = ", ".join(escape(item.display_name) for item in roster.participants) or "нет"
    waitlist = ", ".join(escape(item.display_name) for item in roster.waitlist) or "нет"
    return f"{escape(roster.event.tea_name)}\nПодтверждены: {confirmed}\nЛист ожидания: {waitlist}"
