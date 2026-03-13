from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from tea_party_reservation_bot.application.contracts import UnitOfWork
from tea_party_reservation_bot.application.security import DomainAuthorizationService
from tea_party_reservation_bot.application.services import (
    EventDraftingService,
    EventPersistenceService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    SystemClock,
    UserApplicationService,
)
from tea_party_reservation_bot.application.telegram import TelegramBotApplicationService
from tea_party_reservation_bot.config.settings import Settings
from tea_party_reservation_bot.domain.parsing import AdminEventInputParser
from tea_party_reservation_bot.infrastructure.db import SqlAlchemyUnitOfWork, create_session_factory
from tea_party_reservation_bot.infrastructure.telegram.backends import (
    SqlAlchemyAdminRoleRepository,
    SqlAlchemyEventReadModelPort,
    SqlAlchemyNotificationPreferencePort,
    SqlAlchemyPublicationWorkflowPort,
    SqlAlchemyRegistrationCommandPort,
    SqlAlchemyTelegramUserSyncPort,
)
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.logging import get_logger
from tea_party_reservation_bot.presentation.telegram.handlers import (
    TelegramHandlerDependencies,
    build_router,
)


@dataclass(slots=True)
class BotRuntime:
    settings: Settings

    def run(self) -> None:
        asyncio.run(self._run_polling())

    async def _run_polling(self) -> None:
        logger = get_logger(__name__)
        token = self.settings.telegram.bot_token.get_secret_value()
        if token == "unsafe-placeholder":  # noqa: S105
            msg = "Configure TEA_PARTY_TELEGRAM__BOT_TOKEN before starting the bot."
            raise RuntimeError(msg)
        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        storage = MemoryStorage()
        dispatcher = Dispatcher(storage=storage)
        session_factory = create_session_factory(self.settings.database)
        authorization_service = DomainAuthorizationService()
        clock = SystemClock()

        def uow_factory() -> UnitOfWork:
            return cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))

        event_query_service = EventQueryService(uow_factory, authorization_service, clock)
        event_read_model = SqlAlchemyEventReadModelPort(
            session_factory=session_factory,
            timezone=self.settings.app.timezone,
        )
        application_service = TelegramBotApplicationService(
            roles=SqlAlchemyAdminRoleRepository(session_factory),
            authorization_service=authorization_service,
            drafting_service=EventDraftingService(
                parser=AdminEventInputParser(
                    default_cancel_deadline_offset_minutes=self.settings.app.default_cancel_deadline_offset_minutes
                ),
                authorization_service=authorization_service,
                timezone_name=self.settings.app.timezone_name,
            ),
            user_sync=SqlAlchemyTelegramUserSyncPort(UserApplicationService(uow_factory)),
            events=event_read_model,
            registrations=SqlAlchemyRegistrationCommandPort(
                registration_service=RegistrationService(uow_factory, clock, authorization_service),
                query_service=event_query_service,
                events=event_read_model,
            ),
            notifications=SqlAlchemyNotificationPreferencePort(
                NotificationPreferenceService(uow_factory)
            ),
            publication=SqlAlchemyPublicationWorkflowPort(
                event_persistence_service=EventPersistenceService(
                    uow_factory,
                    authorization_service,
                    self.settings.app.timezone_name,
                ),
                publication_service=PublicationService(uow_factory, authorization_service, clock),
            ),
        )
        me = await bot.get_me()
        dispatcher.include_router(
            build_router(
                TelegramHandlerDependencies(
                    application_service=application_service,
                    publication_renderer=TelegramPublicationRenderer(),
                    bot_username=me.username or "",
                )
            )
        )
        logger.info(
            "bot.runtime.polling_started",
            environment=self.settings.app.env,
            timezone=self.settings.app.timezone_name,
            bot_username=me.username,
        )
        try:
            await dispatcher.start_polling(bot)
        finally:
            bind = session_factory.kw.get("bind")
            if bind is not None:
                await bind.dispose()
            await bot.session.close()
