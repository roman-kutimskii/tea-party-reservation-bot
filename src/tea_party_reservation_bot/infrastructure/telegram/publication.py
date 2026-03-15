from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from tea_party_reservation_bot.application.telegram import PublicEventView
from tea_party_reservation_bot.domain.events import EventPreview
from tea_party_reservation_bot.infrastructure.telegram.deep_links import build_event_deep_link

_TELEGRAM_MESSAGE_LIMIT = 4096
_TELEGRAM_BUTTON_TEXT_LIMIT = 64


def _truncate_button_text(text: str) -> str:
    if len(text) <= _TELEGRAM_BUTTON_TEXT_LIMIT:
        return text
    return f"{text[: _TELEGRAM_BUTTON_TEXT_LIMIT - 3].rstrip()}..."


def _ensure_message_length(text: str) -> str:
    if len(text) <= _TELEGRAM_MESSAGE_LIMIT:
        return text
    msg = "Telegram post exceeds the message length limit."
    raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class TelegramGroupPostPayload:
    text: str
    reply_markup: InlineKeyboardMarkup


class TelegramPublicationRenderer:
    def render_single_event_post(
        self,
        *,
        bot_username: str,
        preview: EventPreview,
        event_id: str,
    ) -> TelegramGroupPostPayload:
        text = self._render_preview_block(preview, prefix=None)
        button = InlineKeyboardButton(
            text=_truncate_button_text(f"Открыть: {preview.normalized.tea_name}"),
            url=build_event_deep_link(bot_username=bot_username, event_id=event_id),
        )
        return TelegramGroupPostPayload(
            text=_ensure_message_length(text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
        )

    def render_batch_post(
        self,
        *,
        bot_username: str,
        previews: Sequence[EventPreview],
        event_ids: Sequence[str],
    ) -> TelegramGroupPostPayload:
        blocks = [
            self._render_preview_block(preview, prefix=f"{index}.")
            for index, preview in enumerate(previews, start=1)
        ]
        buttons = [
            [
                InlineKeyboardButton(
                    text=_truncate_button_text(f"{index}. {preview.normalized.tea_name}"),
                    url=build_event_deep_link(bot_username=bot_username, event_id=event_id),
                )
            ]
            for index, (preview, event_id) in enumerate(
                zip(previews, event_ids, strict=True), start=1
            )
        ]
        return TelegramGroupPostPayload(
            text=_ensure_message_length("\n\n".join(blocks)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    def render_published_event_post(
        self,
        *,
        bot_username: str,
        event: PublicEventView,
    ) -> TelegramGroupPostPayload:
        button_label = _truncate_button_text(f"Записаться: {event.tea_name}")
        button = InlineKeyboardButton(
            text=button_label,
            url=build_event_deep_link(bot_username=bot_username, event_id=event.event_id),
        )
        text = self._render_event_block(event)
        return TelegramGroupPostPayload(
            text=_ensure_message_length(text),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
        )

    def render_published_batch_post(
        self,
        *,
        bot_username: str,
        events: Sequence[PublicEventView],
    ) -> TelegramGroupPostPayload:
        blocks = [
            self._render_event_block(event, prefix=f"{index}.")
            for index, event in enumerate(events, start=1)
        ]
        buttons = [
            [
                InlineKeyboardButton(
                    text=_truncate_button_text(f"{index}. {event.tea_name}"),
                    url=build_event_deep_link(bot_username=bot_username, event_id=event.event_id),
                )
            ]
            for index, event in enumerate(events, start=1)
        ]
        return TelegramGroupPostPayload(
            text=_ensure_message_length("\n\n".join(blocks)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    def _render_preview_block(self, preview: EventPreview, *, prefix: str | None) -> str:
        event = preview.normalized
        lines = [
            f"{prefix} {escape(event.tea_name)}" if prefix else escape(event.tea_name),
            f"Дата: {event.starts_at_local:%d.%m.%Y %H:%M}",
            f"Мест: {event.capacity}",
        ]
        if event.description:
            lines.append(f"Описание: {escape(event.description)}")
        return "\n".join(lines)

    def _render_event_block(self, event: PublicEventView, *, prefix: str | None = None) -> str:
        lines = [
            f"{prefix} {escape(event.tea_name)}" if prefix else escape(event.tea_name),
            f"Дата: {event.starts_at_local:%d.%m.%Y %H:%M}",
            f"Свободно мест: {event.seats_left}",
        ]
        if event.description:
            lines.append(escape(event.description))
        return "\n".join(lines)


class AiogramGroupPublisher:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_group_post(self, *, chat_id: int, payload: TelegramGroupPostPayload) -> Message:
        return await self._bot.send_message(
            chat_id=chat_id,
            text=payload.text,
            reply_markup=payload.reply_markup,
        )


class AiogramTelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_direct_message(self, *, telegram_user_id: int, text: str) -> Message:
        return await self._bot.send_message(chat_id=telegram_user_id, text=text)
