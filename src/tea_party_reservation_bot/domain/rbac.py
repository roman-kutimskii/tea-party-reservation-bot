from __future__ import annotations

from dataclasses import dataclass

from tea_party_reservation_bot.domain.enums import AdminRole, Permission
from tea_party_reservation_bot.exceptions import AuthorizationError

ROLE_PERMISSIONS: dict[AdminRole, frozenset[Permission]] = {
    AdminRole.OWNER: frozenset(
        {
            Permission.VIEW_EVENTS,
            Permission.CREATE_DRAFT,
            Permission.PUBLISH_EVENT,
            Permission.MANAGE_REGISTRATIONS,
            Permission.MANAGE_ADMIN_ROLES,
            Permission.MANAGE_SETTINGS,
        }
    ),
    AdminRole.MANAGER: frozenset(
        {
            Permission.VIEW_EVENTS,
            Permission.CREATE_DRAFT,
            Permission.PUBLISH_EVENT,
            Permission.MANAGE_REGISTRATIONS,
        }
    ),
}


@dataclass(slots=True, frozen=True)
class RoleSet:
    roles: frozenset[AdminRole]

    def permissions(self) -> frozenset[Permission]:
        effective_permissions: set[Permission] = set()
        for role in self.roles:
            effective_permissions.update(ROLE_PERMISSIONS[role])
        return frozenset(effective_permissions)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions()


@dataclass(slots=True, frozen=True)
class Actor:
    telegram_user_id: int
    roles: RoleSet

    def can(self, permission: Permission) -> bool:
        return self.roles.has(permission)


def require_permission(actor: Actor, permission: Permission) -> None:
    if not actor.can(permission):
        msg = "Недостаточно прав для выполнения действия."
        raise AuthorizationError(msg)
