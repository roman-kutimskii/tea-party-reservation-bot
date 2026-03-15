from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
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
from tea_party_reservation_bot.metrics import (
    RuntimeStatus,
    build_app_metrics,
    maybe_start_metrics_http_server,
)


@dataclass(slots=True)
class WorkerRuntime:
    settings: Settings
    scheduler: AsyncIOScheduler

    reconciliation_job_id = "publication-reconciliation"

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
        metrics = build_app_metrics(self.settings.metrics)
        runtime_status = RuntimeStatus(runtime="worker")
        auth = DomainAuthorizationService(metrics=metrics)
        clock = SystemClock()

        def uow_factory() -> UnitOfWork:
            return cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))

        publication_service = PublicationService(
            uow_factory=uow_factory,
            authorization_service=auth,
            clock=clock,
            metrics=metrics,
        )
        maybe_start_metrics_http_server(
            metrics,
            host=self.settings.metrics.host,
            port=self.settings.metrics.worker_port,
            runtime="worker",
            runtime_status=runtime_status,
        )
        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        me = await bot.get_me()
        runtime_status.mark_ready()
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
        processing_lock = asyncio.Lock()

        if self.settings.worker.scheduled_reconciliation_enabled:
            self._configure_scheduled_reconciliation_job(
                processor=processor,
                processing_lock=processing_lock,
            )
            self.scheduler.start()
            logger.info(
                "worker.scheduler.configured",
                timezone=self.settings.app.timezone_name,
                reconciliation_interval_seconds=self.settings.worker.outbox_poll_interval_seconds,
                outbox_batch_size=self.settings.worker.outbox_batch_size,
            )

        logger.info("worker.runtime.started", bot_username=me.username)
        try:
            while True:
                async with processing_lock:
                    processed = await processor.run_once(
                        limit=self.settings.worker.outbox_batch_size
                    )
                logger.info("worker.outbox.tick", processed=processed)
                await asyncio.sleep(self.settings.worker.outbox_poll_interval_seconds)
        finally:
            runtime_status.mark_not_ready(reason="stopped")
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            bind = session_factory.kw.get("bind")
            if bind is not None:
                await bind.dispose()
            await bot.session.close()

    def _configure_scheduled_reconciliation_job(
        self,
        *,
        processor: OutboxProcessor,
        processing_lock: asyncio.Lock,
    ) -> None:
        self.scheduler.add_job(
            self._run_scheduled_reconciliation,
            trigger="interval",
            seconds=self.settings.worker.outbox_poll_interval_seconds,
            id=self.reconciliation_job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(tz=UTC),
            kwargs={"processor": processor, "processing_lock": processing_lock},
        )

    async def _run_scheduled_reconciliation(
        self,
        *,
        processor: OutboxProcessor,
        processing_lock: asyncio.Lock,
    ) -> None:
        async with processing_lock:
            processed = await processor.reconcile_once(limit=self.settings.worker.outbox_batch_size)
        get_logger(__name__).info("worker.reconciliation.tick", processed=processed)
