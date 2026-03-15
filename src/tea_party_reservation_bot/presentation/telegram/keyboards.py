from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from tea_party_reservation_bot.application.telegram import (
    AdminEventView,
    PublicEventView,
    UserRegistrationView,
)

_VISITOR_MENU_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Ближайшие дегустации"), KeyboardButton(text="Мои записи")],
        [KeyboardButton(text="Уведомления"), KeyboardButton(text="Как это работает")],
    ],
    resize_keyboard=True,
)


_ADMIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Создать событие"), KeyboardButton(text="Создать неделю")],
        [KeyboardButton(text="События"), KeyboardButton(text="Участники")],
    ],
    resize_keyboard=True,
)


def visitor_menu_keyboard() -> ReplyKeyboardMarkup:
    return _VISITOR_MENU_KEYBOARD


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return _ADMIN_MENU_KEYBOARD


def event_actions_keyboard(event: PublicEventView) -> InlineKeyboardMarkup:
    primary_label = "На лист ожидания" if event.is_full else "Записаться"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=primary_label, callback_data=f"event:register:{event.event_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Подробнее", callback_data=f"event:detail:{event.event_id}"
                )
            ],
        ]
    )


def notifications_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    label = "Выключить" if enabled else "Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data="notifications:toggle")]]
    )


def registration_cancel_keyboard(registration: UserRegistrationView) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отменить запись",
                    callback_data=f"my:cancel_prompt:{registration.registration_id}",
                )
            ]
        ]
    )


def cancellation_confirm_keyboard(registration_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, отменить",
                    callback_data=f"my:cancel_yes:{registration_id}",
                ),
                InlineKeyboardButton(
                    text="Нет, оставить",
                    callback_data=f"my:cancel_no:{registration_id}",
                ),
            ]
        ]
    )


_DRAFT_PREVIEW_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Опубликовать", callback_data="draft:publish")],
        [InlineKeyboardButton(text="Исправить", callback_data="draft:edit")],
        [InlineKeyboardButton(text="Отмена", callback_data="draft:cancel")],
    ]
)


def draft_preview_keyboard() -> InlineKeyboardMarkup:
    return _DRAFT_PREVIEW_KEYBOARD


def admin_events_keyboard(events: list[AdminEventView]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{event.starts_at_local:%d.%m} {event.tea_name}",
                callback_data=f"admin:roster:{event.event_id}",
            )
        ]
        for event in events
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=rows or [[InlineKeyboardButton(text="Список пуст", callback_data="noop")]]
    )
