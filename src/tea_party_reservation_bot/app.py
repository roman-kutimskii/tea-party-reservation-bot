from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tea_party_reservation_bot.background.runtime import WorkerRuntime
from tea_party_reservation_bot.config.settings import Settings, get_settings
from tea_party_reservation_bot.logging import configure_logging, get_logger
from tea_party_reservation_bot.presentation.telegram.runtime import BotRuntime


class ApplicationMode(StrEnum):
    BOT = "bot"
    WORKER = "worker"


@dataclass(slots=True, frozen=True)
class RuntimeBundle:
    settings: Settings
    scheduler: AsyncIOScheduler
    bot_runtime: BotRuntime
    worker_runtime: WorkerRuntime


def create_runtime(settings: Settings | None = None) -> RuntimeBundle:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    scheduler = AsyncIOScheduler(timezone=resolved_settings.app.timezone)
    return RuntimeBundle(
        settings=resolved_settings,
        scheduler=scheduler,
        bot_runtime=BotRuntime(settings=resolved_settings),
        worker_runtime=WorkerRuntime(settings=resolved_settings, scheduler=scheduler),
    )


def _run_mode(mode: ApplicationMode, runtime: RuntimeBundle) -> int:
    logger = get_logger(__name__)
    runners: dict[ApplicationMode, Callable[[], None]] = {
        ApplicationMode.BOT: runtime.bot_runtime.run,
        ApplicationMode.WORKER: runtime.worker_runtime.run,
    }
    logger.info("runtime.starting", mode=mode.value)
    runners[mode]()
    logger.info("runtime.stopped", mode=mode.value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tea-party-reservation-bot")
    parser.add_argument("mode", choices=[mode.value for mode in ApplicationMode])
    args = parser.parse_args(argv)
    return _run_mode(ApplicationMode(args.mode), create_runtime())
