from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tea_party_reservation_bot.background.runtime import WorkerRuntime
from tea_party_reservation_bot.config.settings import Settings, WorkerSettings


class FakeProcessor:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def reconcile_once(self, *, limit: int = 100) -> int:
        self.calls.append(limit)
        return 1


def test_worker_runtime_registers_reconciliation_job() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    settings = Settings(
        worker=WorkerSettings(
            outbox_poll_interval_seconds=7,
            outbox_batch_size=11,
            scheduled_reconciliation_enabled=True,
        )
    )
    runtime = WorkerRuntime(settings=settings, scheduler=scheduler)
    processor = cast(Any, FakeProcessor())

    runtime._configure_scheduled_reconciliation_job(
        processor=processor,
        processing_lock=asyncio.Lock(),
    )

    job = scheduler.get_job(runtime.reconciliation_job_id)

    assert job is not None
    assert job.trigger.interval.total_seconds() == 7
    assert job.kwargs["processor"] is processor


@pytest.mark.asyncio
async def test_worker_runtime_runs_scheduled_reconciliation_with_batch_limit() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    settings = Settings(worker=WorkerSettings(outbox_batch_size=9))
    runtime = WorkerRuntime(settings=settings, scheduler=scheduler)
    processor = cast(Any, FakeProcessor())

    await runtime._run_scheduled_reconciliation(
        processor=processor,
        processing_lock=asyncio.Lock(),
    )

    assert processor.calls == [9]
