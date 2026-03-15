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
    AdminAuditService,
    AdminEventService,
    AdminRoleManagementService,
    EventDraftingService,
    EventQueryService,
    NotificationPreferenceService,
    PublicationService,
    RegistrationService,
    SystemClock,
    SystemSettingsService,
    UserApplicationService,
)
from tea_party_reservation_bot.application.telegram import TelegramBotApplicationService
from tea_party_reservation_bot.config.settings import Settings
from tea_party_reservation_bot.infrastructure.db import SqlAlchemyUnitOfWork, create_session_factory
from tea_party_reservation_bot.infrastructure.telegram.backends import (
    SqlAlchemyAdminEventCommandPort,
    SqlAlchemyAdminRoleManagementPort,
    SqlAlchemyAdminRoleRepository,
    SqlAlchemyEventReadModelPort,
    SqlAlchemyNotificationPreferencePort,
    SqlAlchemyPublicationWorkflowPort,
    SqlAlchemyRegistrationCommandPort,
    SqlAlchemySystemSettingsManagementPort,
    SqlAlchemyTelegramUserSyncPort,
)
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.logging import get_logger
from tea_party_reservation_bot.metrics import (
    RuntimeStatus,
    build_app_metrics,
    maybe_start_metrics_http_server,
)
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
        metrics = build_app_metrics(self.settings.metrics)
        runtime_status = RuntimeStatus(runtime="bot")
        authorization_service = DomainAuthorizationService(metrics=metrics)
        clock = SystemClock()

        def uow_factory() -> UnitOfWork:
            return cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))

        event_query_service = EventQueryService(uow_factory, authorization_service, clock)
        system_settings_service = SystemSettingsService(uow_factory, authorization_service)
        event_read_model = SqlAlchemyEventReadModelPort(
            session_factory=session_factory,
            timezone=self.settings.app.timezone,
        )
        application_service = TelegramBotApplicationService(
            roles=SqlAlchemyAdminRoleRepository(session_factory),
            authorization_service=authorization_service,
            drafting_service=EventDraftingService(
                default_settings_service=system_settings_service,
                authorization_service=authorization_service,
                timezone_name=self.settings.app.timezone_name,
            ),
            admin_audit=AdminAuditService(uow_factory),
            user_sync=SqlAlchemyTelegramUserSyncPort(UserApplicationService(uow_factory)),
            events=event_read_model,
            registrations=SqlAlchemyRegistrationCommandPort(
                registration_service=RegistrationService(
                    uow_factory,
                    clock,
                    authorization_service,
                    metrics,
                ),
                query_service=event_query_service,
                events=event_read_model,
            ),
            notifications=SqlAlchemyNotificationPreferencePort(
                NotificationPreferenceService(uow_factory)
            ),
            publication=SqlAlchemyPublicationWorkflowPort(
                publication_service=PublicationService(
                    uow_factory,
                    authorization_service,
                    clock,
                    metrics,
                ),
                timezone_name=self.settings.app.timezone_name,
            ),
            admin_commands=SqlAlchemyAdminEventCommandPort(
                service=AdminEventService(uow_factory, authorization_service, clock, metrics),
                registration_service=RegistrationService(
                    uow_factory,
                    clock,
                    authorization_service,
                    metrics,
                ),
                timezone=self.settings.app.timezone,
            ),
            admin_role_management=SqlAlchemyAdminRoleManagementPort(
                AdminRoleManagementService(uow_factory, authorization_service)
            ),
            system_settings_management=SqlAlchemySystemSettingsManagementPort(
                system_settings_service
            ),
        )
        maybe_start_metrics_http_server(
            metrics,
            host=self.settings.metrics.host,
            port=self.settings.metrics.bot_port,
            runtime="bot",
            runtime_status=runtime_status,
        )
        me = await bot.get_me()
        runtime_status.mark_ready()
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
            runtime_status.mark_not_ready(reason="stopped")
            bind = session_factory.kw.get("bind")
            if bind is not None:
                await bind.dispose()
            await bot.session.close()
