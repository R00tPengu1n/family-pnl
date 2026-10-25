from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from family_pnl.api.schemas.auth import Password
from family_pnl.services.telegram import AccessToken, IssuedLinkCode

# Telegram user ids are positive and fit a signed 64-bit integer (the BIGINT column).
TelegramId = Annotated[int, Field(gt=0, lt=2**63)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class LinkCodeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"code": "K7Q2-M9XD", "expires_at": "2026-10-24T09:10:00Z"}]
        }
    )

    code: str = Field(description="Send it to the bot: /link K7Q2-M9XD")
    expires_at: datetime

    @classmethod
    def of(cls, issued: IssuedLinkCode) -> "LinkCodeResponse":
        return cls(code=issued.code, expires_at=issued.expires_at)


class BotLinkRequest(BaseModel):
    code: str = Field(max_length=32)
    telegram_id: TelegramId


class BotRegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"telegram_id": 5000000001, "display_name": "Anna", "household_name": "Ivanovs"}
            ]
        }
    )

    telegram_id: TelegramId
    display_name: Name | None = None
    household_name: Name = "Family"
    invite_code: str | None = Field(default=None, max_length=64)


class BotCredentialsCodeRequest(BaseModel):
    telegram_id: TelegramId


class CredentialsRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "K7Q2-M9XD",
                    "email": "anna@example.com",
                    "password": "correct horse battery",
                }
            ]
        }
    )

    code: str = Field(max_length=32, description="From /password in the bot")
    email: EmailStr
    password: str = Password


class BotTokenRequest(BaseModel):
    telegram_id: TelegramId


class BotTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = Field(default="bearer")
    expires_in: int

    @classmethod
    def of(cls, token: AccessToken) -> "BotTokenResponse":
        return cls(access_token=token.access_token, expires_in=token.expires_in)
