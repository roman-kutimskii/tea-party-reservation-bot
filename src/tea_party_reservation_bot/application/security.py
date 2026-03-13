from tea_party_reservation_bot.application.contracts import AuthorizationService
from tea_party_reservation_bot.domain.enums import Permission
from tea_party_reservation_bot.domain.rbac import Actor, require_permission


class DomainAuthorizationService(AuthorizationService):
    def require(self, actor: Actor, permission: Permission) -> None:
        require_permission(actor, permission)
