import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from family_pnl.domain.currency import Currency
from family_pnl.domain.identity import MAX_PASSWORD_LENGTH, Role
from family_pnl.services.auth import CurrentUser, TokenPair

# The policy itself lives in the domain; this bound only keeps hostile input small.
Password = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "anna@example.com",
                    "password": "correct horse battery",
                    "household_name": "Ivanovs",
                }
            ]
        }
    )

    email: EmailStr
    password: str = Password
    household_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ] = "Family"


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "anna@example.com", "password": "correct horse battery"}]
        }
    )

    email: EmailStr
    password: str = Password


class RefreshRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"refresh_token": "<refresh_token from POST /auth/login>"}]}
    )

    refresh_token: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = Field(default="bearer")
    expires_in: int = Field(description="Access token lifetime in seconds")

    @classmethod
    def of(cls, tokens: TokenPair) -> "TokenResponse":
        return cls(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    base_currency: Currency


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str | None = Field(description="Empty for accounts created through Telegram")
    display_name: str | None
    telegram_linked: bool
    role: Role
    household: HouseholdOut

    @classmethod
    def of(cls, user: CurrentUser) -> "MeResponse":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            telegram_linked=user.telegram_linked,
            role=user.role,
            household=HouseholdOut(
                id=user.household_id,
                name=user.household_name,
                timezone=user.household_timezone,
                base_currency=user.household_base_currency,
            ),
        )
