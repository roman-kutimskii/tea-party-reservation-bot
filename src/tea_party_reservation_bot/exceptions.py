class TeaPartyError(Exception):
    pass


class DomainError(TeaPartyError):
    pass


class ValidationError(TeaPartyError):
    pass


class AuthorizationError(TeaPartyError):
    pass


class ApplicationError(TeaPartyError):
    pass


class NotFoundError(ApplicationError):
    pass


class ConflictError(ApplicationError):
    pass
