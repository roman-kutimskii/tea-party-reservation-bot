from __future__ import annotations

import asyncio
import sys
import warnings
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, cast

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tea_party_reservation_bot.application.contracts import UnitOfWork
from tea_party_reservation_bot.application.dto import TelegramProfile
from tea_party_reservation_bot.application.security import DomainAuthorizationService
from tea_party_reservation_bot.application.services import (
    AdminAccessService,
    AdminEventService,
    AdminRoleManagementService,
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    SystemClock,
    SystemSettingsService,
    UserApplicationService,
)
from tea_party_reservation_bot.config.settings import DatabaseSettings
from tea_party_reservation_bot.infrastructure.db import create_session_factory
from tea_party_reservation_bot.infrastructure.db.models import RoleAssignmentModel, RoleModel
from tea_party_reservation_bot.infrastructure.db.uow import SqlAlchemyUnitOfWork


def _async_dsn(container: PostgresContainer) -> str:
    dsn = container.get_connection_url()
    return dsn.replace("+psycopg2", "+psycopg")


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform != "win32":
        return asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return selector_policy()


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield _async_dsn(container)


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(postgres_dsn: str) -> None:
    config = Config()
    config.set_main_option(
        "script_location",
        "src/tea_party_reservation_bot/infrastructure/db/migrations",
    )
    config.set_main_option("sqlalchemy.url", postgres_dsn)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def session_factory(postgres_dsn: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = create_session_factory(DatabaseSettings(dsn=postgres_dsn, echo=False))
    yield factory
    bind = factory.kw.get("bind")
    if bind is not None:
        await bind.dispose()


@pytest_asyncio.fixture
async def db_cleanup(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    async with session_factory() as session:
        for table in [
            "admin_audit_log",
            "outbox_events",
            "processed_commands",
            "reservations",
            "waitlist_entries",
            "publication_batch_events",
            "event_occurrences",
            "publication_batches",
            "notification_preferences",
            "system_settings",
            "role_assignments",
            "users",
        ]:
            await session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        await session.execute(
            text(
                "INSERT INTO system_settings "
                "(id, default_cancel_deadline_offset_minutes, created_at, updated_at) "
                "VALUES (1, 240, now(), now())"
            )
        )
        await session.commit()
    yield


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession], db_cleanup: None
) -> Callable[[], SqlAlchemyUnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(session_factory)


@pytest_asyncio.fixture
async def seed_admin(session_factory: async_sessionmaker[AsyncSession], db_cleanup: None) -> None:
    user_service = UserApplicationService(
        cast(Any, lambda: cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory)))
    )
    admin = await user_service.ensure_user(
        TelegramProfile(
            telegram_user_id=1000,
            username="owner",
            first_name="Owner",
            last_name=None,
        )
    )
    async with session_factory() as session:
        role_id = await session.scalar(select(RoleModel.id).where(RoleModel.code == "owner"))
        if role_id is None:
            raise AssertionError("owner role not found")
        session.add(RoleAssignmentModel(user_id=admin.id, role_id=role_id))
        await session.commit()


@pytest.fixture
def services(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork], seed_admin: None
) -> dict[str, object]:
    auth = DomainAuthorizationService()
    clock = SystemClock()
    typed_uow_factory = cast(Any, uow_factory)
    return {
        "user": UserApplicationService(typed_uow_factory),
        "admin_access": AdminAccessService(typed_uow_factory),
        "admin_roles": AdminRoleManagementService(typed_uow_factory, auth),
        "events": EventPersistenceService(typed_uow_factory, auth, "Europe/Moscow"),
        "publication": PublicationService(typed_uow_factory, auth, clock),
        "query": EventQueryService(typed_uow_factory, auth, clock),
        "admin_events": AdminEventService(typed_uow_factory, auth, clock),
        "system_settings": SystemSettingsService(typed_uow_factory, auth),
        "notifications": NotificationPreferenceService(typed_uow_factory),
        "registration": RegistrationService(typed_uow_factory, clock, auth),
    }
