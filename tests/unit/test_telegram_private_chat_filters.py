from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from tea_party_reservation_bot.application.telegram import TelegramBotApplicationService
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.presentation.telegram.handlers import (
    TelegramHandlerDependencies,
    build_router,
)


def _build_message(*, chat_type: str, text: str, message_id: int = 1) -> Message:
    now = datetime.now(tz=UTC)
    return Message(
        message_id=message_id,
        date=now,
        chat=Chat(id=100 if chat_type == "private" else -100, type=chat_type),
        from_user=User(id=42, is_bot=False, first_name="Guest"),
        text=text,
    )


def _build_callback(*, chat_type: str, data: str) -> CallbackQuery:
    return CallbackQuery(
        id="callback-1",
        from_user=User(id=42, is_bot=False, first_name="Guest"),
        chat_instance="chat-instance",
        data=data,
        message=_build_message(chat_type=chat_type, text="button", message_id=2),
    )


def _build_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token="123456:TEST")  # noqa: S106
    application_service = cast(
        TelegramBotApplicationService, SimpleNamespace(sync_profile=AsyncMock())
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_router(
            TelegramHandlerDependencies(
                application_service=application_service,
                publication_renderer=TelegramPublicationRenderer(),
                bot_username="tea_party_bot",
            )
        )
    )
    return bot, dispatcher


@pytest.mark.asyncio
async def test_bot_ignores_group_messages() -> None:
    bot, dispatcher = _build_dispatcher()
    mock_send = AsyncMock()
    setattr(bot, "send_message", mock_send)

    update = Update(update_id=1, message=_build_message(chat_type="group", text="/help"))
    await dispatcher.feed_update(bot, update)

    mock_send.assert_not_awaited()
    await bot.session.close()


@pytest.mark.asyncio
async def test_bot_replies_in_private_chat() -> None:
    bot, dispatcher = _build_dispatcher()
    mock_make_request = AsyncMock(return_value=None)
    setattr(bot.session, "make_request", mock_make_request)

    update = Update(update_id=1, message=_build_message(chat_type="private", text="/help"))
    await dispatcher.feed_update(bot, update)

    mock_make_request.assert_awaited_once()
    await bot.session.close()


@pytest.mark.asyncio
async def test_bot_ignores_group_callbacks() -> None:
    bot, dispatcher = _build_dispatcher()
    mock_answer = AsyncMock()
    setattr(bot, "answer_callback_query", mock_answer)

    update = Update(update_id=1, callback_query=_build_callback(chat_type="group", data="noop"))
    await dispatcher.feed_update(bot, update)

    mock_answer.assert_not_awaited()
    await bot.session.close()
