from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message

from tea_party_reservation_bot.application.telegram import PublicEventView
from tea_party_reservation_bot.domain.events import EventPreview
from tea_party_reservation_bot.infrastructure.telegram.deep_links import build_event_deep_link

_TELEGRAM_MESSAGE_LIMIT = 4096


class PostingRightsMissingError(RuntimeError):
    pass


def _ensure_message_length(text: str) -> str:
    if len(text) <= _TELEGRAM_MESSAGE_LIMIT:
        return text
    msg = "Telegram post exceeds the message length limit."
    raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class TelegramDeepLinkPreview:
    label: str
    url: str


@dataclass(slots=True, frozen=True)
class TelegramGroupPostPayload:
    text: str
    preview_text: str
    deep_links: tuple[TelegramDeepLinkPreview, ...] = ()
    reply_markup: InlineKeyboardMarkup | None = None


def _render_hidden_link(*, label: str, url: str) -> str:
    safe_url = quote(url, safe=":/?&=%#-._~")
    return f'<a href="{safe_url}">{escape(label)}</a>'


class TelegramPublicationRenderer:
    def render_single_event_post(
        self,
        *,
        bot_username: str,
        preview: EventPreview,
        event_id: str,
    ) -> TelegramGroupPostPayload:
        registration_url = build_event_deep_link(bot_username=bot_username, event_id=event_id)
        text = self._render_preview_block(
            preview,
            prefix=None,
            registration_line=_render_hidden_link(
                label="Открыть регистрацию",
                url=registration_url,
            ),
        )
        preview_text = self._render_preview_block(
            preview,
            prefix=None,
            registration_line="Открыть регистрацию",
        )
        return TelegramGroupPostPayload(
            text=_ensure_message_length(text),
            preview_text=preview_text,
            deep_links=(
                TelegramDeepLinkPreview(label=preview.normalized.tea_name, url=registration_url),
            ),
        )

    def render_batch_post(
        self,
        *,
        bot_username: str,
        previews: Sequence[EventPreview],
        event_ids: Sequence[str],
    ) -> TelegramGroupPostPayload:
        blocks: list[str] = []
        preview_blocks: list[str] = []
        deep_links: list[TelegramDeepLinkPreview] = []
        for index, (preview, event_id) in enumerate(
            zip(previews, event_ids, strict=True),
            start=1,
        ):
            registration_url = build_event_deep_link(
                bot_username=bot_username,
                event_id=event_id,
            )
            prefix = f"{index}."
            blocks.append(
                self._render_preview_block(
                    preview,
                    prefix=prefix,
                    registration_line=_render_hidden_link(
                        label="Открыть регистрацию",
                        url=registration_url,
                    ),
                )
            )
            preview_blocks.append(
                self._render_preview_block(
                    preview,
                    prefix=prefix,
                    registration_line="Открыть регистрацию",
                )
            )
            deep_links.append(
                TelegramDeepLinkPreview(
                    label=f"{index}. {preview.normalized.tea_name}", url=registration_url
                )
            )
        return TelegramGroupPostPayload(
            text=_ensure_message_length("\n\n".join(blocks)),
            preview_text="\n\n".join(preview_blocks),
            deep_links=tuple(deep_links),
        )

    def render_published_event_post(
        self,
        *,
        bot_username: str,
        event: PublicEventView,
    ) -> TelegramGroupPostPayload:
        registration_url = build_event_deep_link(bot_username=bot_username, event_id=event.event_id)
        text = self._render_event_block(
            event,
            registration_line=_render_hidden_link(
                label="Открыть регистрацию",
                url=registration_url,
            ),
        )
        preview_text = self._render_event_block(
            event,
            registration_line="Открыть регистрацию",
        )
        return TelegramGroupPostPayload(
            text=_ensure_message_length(text),
            preview_text=preview_text,
            deep_links=(TelegramDeepLinkPreview(label=event.tea_name, url=registration_url),),
        )

    def render_published_batch_post(
        self,
        *,
        bot_username: str,
        events: Sequence[PublicEventView],
    ) -> TelegramGroupPostPayload:
        blocks: list[str] = []
        preview_blocks: list[str] = []
        deep_links: list[TelegramDeepLinkPreview] = []
        for index, event in enumerate(events, start=1):
            registration_url = build_event_deep_link(
                bot_username=bot_username,
                event_id=event.event_id,
            )
            prefix = f"{index}."
            blocks.append(
                self._render_event_block(
                    event,
                    prefix=prefix,
                    registration_line=_render_hidden_link(
                        label="Открыть регистрацию",
                        url=registration_url,
                    ),
                )
            )
            preview_blocks.append(
                self._render_event_block(
                    event,
                    prefix=prefix,
                    registration_line="Открыть регистрацию",
                )
            )
            deep_links.append(
                TelegramDeepLinkPreview(label=f"{index}. {event.tea_name}", url=registration_url)
            )
        return TelegramGroupPostPayload(
            text=_ensure_message_length("\n\n".join(blocks)),
            preview_text="\n\n".join(preview_blocks),
            deep_links=tuple(deep_links),
        )

    def _render_preview_block(
        self,
        preview: EventPreview,
        *,
        prefix: str | None,
        registration_line: str | None = None,
    ) -> str:
        event = preview.normalized
        lines = [
            f"{prefix} {escape(event.tea_name)}" if prefix else escape(event.tea_name),
            f"Дата: {event.starts_at_local:%d.%m.%Y %H:%M}",
            f"Мест: {event.capacity}",
        ]
        if event.description:
            lines.append(f"Описание: {escape(event.description)}")
        if registration_line:
            lines.append(registration_line)
        return "\n".join(lines)

    def _render_event_block(
        self,
        event: PublicEventView,
        *,
        prefix: str | None = None,
        registration_line: str | None = None,
    ) -> str:
        lines = [
            f"{prefix} {escape(event.tea_name)}" if prefix else escape(event.tea_name),
            f"Дата: {event.starts_at_local:%d.%m.%Y %H:%M}",
            f"Свободно мест: {event.seats_left}",
        ]
        if event.description:
            lines.append(escape(event.description))
        if registration_line:
            lines.append(registration_line)
        return "\n".join(lines)


class AiogramGroupPublisher:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_group_post(self, *, chat_id: int, payload: TelegramGroupPostPayload) -> Message:
        try:
            return await self._bot.send_message(
                chat_id=chat_id,
                text=payload.text,
                reply_markup=payload.reply_markup,
            )
        except TelegramForbiddenError as exc:
            msg = "Missing rights to publish messages in the configured Telegram chat."
            raise PostingRightsMissingError(msg) from exc

    async def edit_group_post(
        self,
        *,
        chat_id: int,
        message_id: int,
        payload: TelegramGroupPostPayload,
    ) -> Message:
        try:
            result = await self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=payload.text,
                reply_markup=payload.reply_markup,
            )
        except TelegramForbiddenError as exc:
            msg = "Missing rights to edit messages in the configured Telegram chat."
            raise PostingRightsMissingError(msg) from exc
        except TelegramBadRequest:
            raise
        if isinstance(result, bool):
            msg = "Expected Telegram to return the edited message instance."
            raise RuntimeError(msg)
        return result

    async def delete_group_post(self, *, chat_id: int, message_id: int) -> bool:
        try:
            return await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramForbiddenError as exc:
            msg = "Missing rights to delete messages in the configured Telegram chat."
            raise PostingRightsMissingError(msg) from exc


class AiogramTelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_direct_message(self, *, telegram_user_id: int, text: str) -> Message:
        return await self._bot.send_message(chat_id=telegram_user_id, text=text)
