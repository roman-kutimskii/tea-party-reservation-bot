from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tea_party_reservation_bot.infrastructure.db.repositories import (
    AuditLogRepository,
    EventRepository,
    IdempotencyRepository,
    NotificationPreferenceRepository,
    OutboxRepository,
    PublicationRepository,
    RegistrationRepository,
    RoleRepository,
    SystemSettingsRepository,
    UserRepository,
)


@dataclass(slots=True)
class SqlAlchemyUnitOfWork:
    session_factory: async_sessionmaker[AsyncSession]
    session: AsyncSession | None = field(default=None, init=False)
    users: UserRepository = field(init=False)
    roles: RoleRepository = field(init=False)
    settings: SystemSettingsRepository = field(init=False)
    events: EventRepository = field(init=False)
    registrations: RegistrationRepository = field(init=False)
    publications: PublicationRepository = field(init=False)
    notifications: NotificationPreferenceRepository = field(init=False)
    outbox: OutboxRepository = field(init=False)
    idempotency: IdempotencyRepository = field(init=False)
    audit_log: AuditLogRepository = field(init=False)

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self.session = self.session_factory()
        self.users = UserRepository(self.session)
        self.roles = RoleRepository(self.session)
        self.settings = SystemSettingsRepository(self.session)
        self.events = EventRepository(self.session)
        self.registrations = RegistrationRepository(self.session)
        self.publications = PublicationRepository(self.session)
        self.notifications = NotificationPreferenceRepository(self.session)
        self.outbox = OutboxRepository(self.session)
        self.idempotency = IdempotencyRepository(self.session)
        self.audit_log = AuditLogRepository(self.session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.session is None:
            return
        try:
            if exc is not None:
                await self.session.rollback()
            else:
                await self.session.commit()
        finally:
            await self.session.close()
            self.session = None

    async def commit(self) -> None:
        if self.session is None:
            return
        await self.session.commit()

    async def rollback(self) -> None:
        if self.session is None:
            return
        await self.session.rollback()
