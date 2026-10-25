"""Bot settings from `FAMILY_PNL_*` environment variables (or `.env`)."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FAMILY_PNL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # A validation error must not print the values: they include secrets.
        hide_input_in_errors=True,
    )

    # From @BotFather; the same token the worker sends notifications with.
    telegram_bot_token: SecretStr
    # Shared with the API (ADR-0007): identifies the bot, carries no user rights.
    bot_api_secret: SecretStr
    api_url: str = "http://127.0.0.1:8000"
    # /link codes can only be tried through the bot, so the bot limits the attempts.
    link_max_attempts: int = Field(default=5, ge=1)
    link_window_seconds: int = Field(default=15 * 60, ge=1)
