from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from tea_party_reservation_bot.application.dto import TelegramProfile
from tea_party_reservation_bot.application.security import DomainAuthorizationService
from tea_party_reservation_bot.application.services import (
    AdminAccessService,
    EventPersistenceService,
    PublicationService,
    RegistrationService,
    SystemClock,
)
from tea_party_reservation_bot.domain.enums import CancelDeadlineSource, Permission
from tea_party_reservation_bot.domain.events import EventDraft
from tea_party_reservation_bot.domain.rbac import Actor, RoleSet
from tea_party_reservation_bot.exceptions import AuthorizationError
from tea_party_reservation_bot.metrics import AppMetrics


@dataclass(slots=True)
class FakeMetrics(AppMetrics):
    registrations: int = 0
    waitlist_joins: int = 0
    promotions: int = 0
    publication_failures: int = 0
    cancellations: Counter[str] = field(default_factory=Counter)
    auth_denials: Counter[str] = field(default_factory=Counter)
    duplicate_suppressions: Counter[str] = field(default_factory=Counter)

    def record_registration(self, *, amount: int = 1) -> None:
        self.registrations += amount

    def record_waitlist_join(self, *, amount: int = 1) -> None:
        self.waitlist_joins += amount

    def record_promotion(self, *, amount: int = 1) -> None:
        self.promotions += amount

    def record_cancellation(self, *, target: str, amount: int = 1) -> None:
        self.cancellations[target] += amount

    def record_publication_failure(self, *, amount: int = 1) -> None:
        self.publication_failures += amount

    def record_auth_denial(self, *, permission: str, amount: int = 1) -> None:
        self.auth_denials[permission] += amount

    def record_duplicate_suppression(self, *, source: str, amount: int = 1) -> None:
        self.duplicate_suppressions[source] += amount


async def _create_published_event(
    services: dict[str, object],
    *,
    capacity: int,
) -> int:
    admin_access = cast(AdminAccessService, services["admin_access"])
    event_service = cast(EventPersistenceService, services["events"])
    publication_service = cast(PublicationService, services["publication"])

    actor = await admin_access.load_actor(1000)
    start = datetime.now(tz=UTC) + timedelta(days=3)
    draft = EventDraft(
        tea_name="Metric Tea",
        description="Metrics coverage",
        starts_at_local=start,
        starts_at_utc=start,
        capacity=capacity,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=start - timedelta(hours=4),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key=f"publish-{saved.event_ids[0]}",
    )
    await publication_service.mark_publication_succeeded(
        batch_id=requested.batch_id or 0,
        event_ids=list(requested.event_ids),
        chat_id=-100123,
        message_id=999,
    )
    return saved.event_ids[0]


@pytest.mark.asyncio
async def test_registration_metrics_cover_waitlist_promotion_cancellation_and_duplicates(
    services: dict[str, object],
    uow_factory: object,
) -> None:
    event_id = await _create_published_event(services, capacity=1)
    metrics = FakeMetrics()
    registration_service = RegistrationService(
        cast(Any, uow_factory),
        SystemClock(),
        metrics=metrics,
    )

    first = await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=2001,
            username="guest1",
            first_name="Guest",
            last_name=None,
        ),
        event_id=event_id,
        idempotency_key="register-1",
    )
    second = await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=2001,
            username="guest1",
            first_name="Guest",
            last_name=None,
        ),
        event_id=event_id,
        idempotency_key="register-1",
    )
    waitlisted = await registration_service.register(
        profile=TelegramProfile(
            telegram_user_id=2002,
            username="guest2",
            first_name="Wait",
            last_name=None,
        ),
        event_id=event_id,
        idempotency_key="register-2",
    )
    cancelled = await registration_service.cancel(
        telegram_user_id=2001,
        event_id=event_id,
        idempotency_key="cancel-1",
    )

    assert first == second
    assert waitlisted.outcome == "waitlisted"
    assert cancelled.promoted_user_id is not None
    assert metrics.registrations == 1
    assert metrics.waitlist_joins == 1
    assert metrics.promotions == 1
    assert metrics.cancellations == Counter({"reservation": 1})
    assert metrics.duplicate_suppressions == Counter({"register": 1})


@pytest.mark.asyncio
async def test_publication_failure_metric_is_recorded(
    services: dict[str, object],
    uow_factory: object,
) -> None:
    metrics = FakeMetrics()
    auth = DomainAuthorizationService(metrics=metrics)
    publication_service = PublicationService(cast(Any, uow_factory), auth, SystemClock(), metrics)
    admin_access = cast(AdminAccessService, services["admin_access"])
    event_service = cast(EventPersistenceService, services["events"])
    actor = await admin_access.load_actor(1000)
    start = datetime.now(tz=UTC) + timedelta(days=4)
    draft = EventDraft(
        tea_name="Failure Tea",
        description="Failed publication",
        starts_at_local=start,
        starts_at_utc=start,
        capacity=2,
        cancel_deadline_source=CancelDeadlineSource.DEFAULT,
        cancel_deadline_at_local=start - timedelta(hours=4),
        cancel_deadline_at_utc=start - timedelta(hours=4),
    )
    saved = await event_service.save_drafts(actor, [draft])
    requested = await publication_service.request_single_event_publication(
        actor=actor,
        event_id=saved.event_ids[0],
        idempotency_key="publish-failure-metric",
    )

    await publication_service.mark_publication_failed(
        batch_id=requested.batch_id or 0,
        event_ids=list(requested.event_ids),
    )

    assert metrics.publication_failures == 1


def test_auth_denial_metric_is_recorded() -> None:
    metrics = FakeMetrics()
    auth = DomainAuthorizationService(metrics=metrics)
    actor = Actor(telegram_user_id=42, roles=RoleSet(frozenset()))

    with pytest.raises(AuthorizationError):
        auth.require(actor, Permission.VIEW_EVENTS)

    assert metrics.auth_denials == Counter({"view_events": 1})
