from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tea_party_reservation_bot.application.contracts import UnitOfWork
from tea_party_reservation_bot.application.security import DomainAuthorizationService
from tea_party_reservation_bot.application.services import (
    PublicationService,
    SystemClock,
)
from tea_party_reservation_bot.background.processor import OutboxProcessor
from tea_party_reservation_bot.config.settings import Settings
from tea_party_reservation_bot.infrastructure.db import SqlAlchemyUnitOfWork, create_session_factory
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    AiogramGroupPublisher,
    AiogramTelegramNotifier,
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.logging import get_logger


@dataclass(slots=True)
class WorkerRuntime:
    settings: Settings
    scheduler: AsyncIOScheduler

    def run(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        logger = get_logger(__name__)
        token = self.settings.telegram.bot_token.get_secret_value()
        if token == "unsafe-placeholder":  # noqa: S105
            msg = "Configure TEA_PARTY_TELEGRAM__BOT_TOKEN before starting the worker."
            raise RuntimeError(msg)
        if self.settings.telegram.group_chat_id is None:
            msg = "Configure TEA_PARTY_TELEGRAM__GROUP_CHAT_ID before starting the worker."
            raise RuntimeError(msg)

        session_factory = create_session_factory(self.settings.database)
        auth = DomainAuthorizationService()
        clock = SystemClock()

        def uow_factory() -> UnitOfWork:
            return cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))

        publication_service = PublicationService(
            uow_factory=uow_factory,
            authorization_service=auth,
            clock=clock,
        )
        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        me = await bot.get_me()
        processor = OutboxProcessor(
            session_factory=session_factory,
            publication_service=publication_service,
            group_publisher=AiogramGroupPublisher(bot),
            notifier=AiogramTelegramNotifier(bot),
            publication_renderer=TelegramPublicationRenderer(),
            bot_username=me.username or "",
            group_chat_id=self.settings.telegram.group_chat_id,
            timezone_name=self.settings.app.timezone_name,
            clock=clock,
            retry_delay_seconds=self.settings.worker.outbox_retry_delay_seconds,
        )

        if self.settings.worker.scheduled_reconciliation_enabled:
            self.scheduler.start()
            logger.info(
                "worker.scheduler.configured",
                timezone=self.settings.app.timezone_name,
                outbox_poll_interval_seconds=self.settings.worker.outbox_poll_interval_seconds,
            )

        logger.info("worker.runtime.started", bot_username=me.username)
        try:
            while True:
                processed = await processor.run_once(limit=self.settings.worker.outbox_batch_size)
                logger.info("worker.outbox.tick", processed=processed)
                await asyncio.sleep(self.settings.worker.outbox_poll_interval_seconds)
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            bind = session_factory.kw.get("bind")
            if bind is not None:
                await bind.dispose()
            await bot.session.close()
