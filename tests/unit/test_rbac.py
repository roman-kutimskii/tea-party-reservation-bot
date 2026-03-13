from __future__ import annotations

import pytest

from tea_party_reservation_bot.domain.enums import AdminRole, Permission
from tea_party_reservation_bot.domain.rbac import Actor, RoleSet, require_permission
from tea_party_reservation_bot.exceptions import AuthorizationError


def test_manager_has_expected_permissions() -> None:
    actor = Actor(telegram_user_id=1, roles=RoleSet(frozenset({AdminRole.MANAGER})))

    assert actor.can(Permission.CREATE_DRAFT)
    assert actor.can(Permission.PUBLISH_EVENT)
    assert not actor.can(Permission.MANAGE_SETTINGS)


def test_require_permission_rejects_missing_permission() -> None:
    actor = Actor(telegram_user_id=1, roles=RoleSet(frozenset({AdminRole.MANAGER})))

    with pytest.raises(AuthorizationError, match="Недостаточно прав"):
        require_permission(actor, Permission.MANAGE_ADMIN_ROLES)
