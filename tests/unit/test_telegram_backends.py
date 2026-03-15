from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from tea_party_reservation_bot.application.services import CancellationResult
from tea_party_reservation_bot.domain.rbac import Actor, RoleSet
from tea_party_reservation_bot.infrastructure.telegram.backends import (
    SqlAlchemyAdminEventCommandPort,
)
from tea_party_reservation_bot.time import load_timezone


@dataclass(slots=True)
class FakeRegistrationService:
    call: dict[str, Any] | None = None

    async def cancel(self, **kwargs: Any) -> CancellationResult:
        self.call = kwargs
        return CancellationResult(
            event_id=kwargs["event_id"],
            user_id=1,
            cancelled_reservation_id=2,
            promoted_user_id=None,
            promoted_telegram_user_id=None,
            message="Запись отменена.",
        )


@pytest.mark.asyncio
async def test_admin_event_command_port_uses_override_for_operational_cancellation() -> None:
    registration_service = FakeRegistrationService()
    port = SqlAlchemyAdminEventCommandPort(
        service=object(),
        registration_service=registration_service,
        timezone=load_timezone("Europe/Moscow"),
    )
    actor = Actor(telegram_user_id=1000, roles=RoleSet(frozenset()))

    result = await port.override_participant_cancellation(
        actor=actor,
        event_id="15",
        telegram_user_id="2002",
        idempotency_key="admin-override-1",
    )

    assert result == "Запись отменена."
    assert registration_service.call == {
        "telegram_user_id": 2002,
        "event_id": 15,
        "idempotency_key": "admin-override-1",
        "override_deadline": True,
        "actor": actor,
    }
