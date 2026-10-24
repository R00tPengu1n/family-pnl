"""Application settings read from environment variables (prefix `FAMILY_PNL_`) and `.env`."""

from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FAMILY_PNL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = "INFO"
    log_json: bool = False
    default_timezone: str = "Europe/Minsk"
    # Contains the password, hence SecretStr: hidden in repr and logs.
    database_url: SecretStr
    # HS256 signing key; at least 32 characters (the length of its 256-bit output).
    jwt_secret: SecretStr
    access_token_ttl_minutes: int = Field(default=15, ge=1)
    refresh_token_ttl_days: int = Field(default=30, ge=1)
    # May contain a password, hence SecretStr.
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    login_max_failures: int = Field(default=5, ge=1)
    login_failure_window_seconds: int = Field(default=15 * 60, ge=1)
    # Shared secret of the Telegram bot (X-Bot-Token); bot endpoints are off without it.
    bot_api_secret: SecretStr | None = None
    nbrb_base_url: str = "https://api.nbrb.by"

    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_ttl_minutes)

    @property
    def refresh_token_ttl(self) -> timedelta:
        return timedelta(days=self.refresh_token_ttl_days)

    @property
    def login_failure_window(self) -> timedelta:
        return timedelta(seconds=self.login_failure_window_seconds)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("default_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone: {value}") from exc
        return value

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must start with postgresql+asyncpg://")
        return value

    @field_validator("redis_url")
    @classmethod
    def _redis_scheme(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must start with redis:// or rediss://")
        return value

    @field_validator("jwt_secret", "bot_api_secret")
    @classmethod
    def _long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("secrets must have at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
