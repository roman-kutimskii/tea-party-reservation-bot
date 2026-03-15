from __future__ import annotations

from datetime import tzinfo
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tea_party_reservation_bot.time import load_timezone


class AppSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    env: Literal["local", "stage", "prod"] = "local"
    timezone_name: str = "Europe/Moscow"
    default_cancel_deadline_offset_minutes: int = Field(default=240, ge=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @property
    def timezone(self) -> tzinfo:
        return load_timezone(self.timezone_name)


class TelegramSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    bot_token: SecretStr = SecretStr("unsafe-placeholder")
    group_chat_id: int | None = None
    owner_user_ids: tuple[int, ...] = ()
    manager_user_ids: tuple[int, ...] = ()


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    dsn: str = "postgresql+psycopg://postgres:postgres@localhost:5432/tea_party"
    echo: bool = False


class WorkerSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    outbox_poll_interval_seconds: int = Field(default=5, ge=1)
    outbox_batch_size: int = Field(default=50, ge=1, le=500)
    outbox_retry_delay_seconds: int = Field(default=30, ge=1)
    scheduled_reconciliation_enabled: bool = True


class MetricsSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    host: str = "127.0.0.1"
    bot_port: int = Field(default=9101, ge=1, le=65535)
    worker_port: int = Field(default=9102, ge=1, le=65535)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEA_PARTY_",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    app: AppSettings = AppSettings()
    telegram: TelegramSettings = TelegramSettings()
    database: DatabaseSettings = DatabaseSettings()
    worker: WorkerSettings = WorkerSettings()
    metrics: MetricsSettings = MetricsSettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
