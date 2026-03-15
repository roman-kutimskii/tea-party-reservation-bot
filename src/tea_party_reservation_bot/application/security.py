from tea_party_reservation_bot.application.contracts import AuthorizationService
from tea_party_reservation_bot.domain.enums import Permission
from tea_party_reservation_bot.domain.rbac import Actor, require_permission
from tea_party_reservation_bot.exceptions import AuthorizationError
from tea_party_reservation_bot.metrics import NO_OP_METRICS, AppMetrics


class DomainAuthorizationService(AuthorizationService):
    def __init__(self, metrics: AppMetrics = NO_OP_METRICS) -> None:
        self.metrics = metrics

    def require(self, actor: Actor, permission: Permission) -> None:
        try:
            require_permission(actor, permission)
        except AuthorizationError:
            self.metrics.record_auth_denial(permission=permission.value)
            raise
