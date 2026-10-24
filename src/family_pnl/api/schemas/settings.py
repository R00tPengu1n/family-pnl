from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from family_pnl.core.config import Settings
from family_pnl.domain.currency import Currency
from family_pnl.models import Household
from family_pnl.services.auth import CurrentUser

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class HouseholdSettingsOut(BaseModel):
    name: str
    base_currency: Currency
    timezone: str

    @classmethod
    def of(cls, household: Household) -> "HouseholdSettingsOut":
        return cls(
            name=household.name,
            base_currency=household.base_currency,
            timezone=household.timezone,
        )


class HouseholdSettingsIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"base_currency": "BYN", "timezone": "Europe/Minsk"}]},
    )

    name: Name | None = None
    base_currency: Currency | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        # The same rule as the application default (IANA names only).
        return value if value is None else Settings.check_timezone(value)


class MemberSettingsOut(BaseModel):
    display_currency: Currency
    input_currency: Currency
    display_currency_set: bool
    input_currency_set: bool

    @classmethod
    def of(cls, user: CurrentUser) -> "MemberSettingsOut":
        return cls(
            display_currency=user.display_currency,
            input_currency=user.input_currency,
            display_currency_set=user.display_currency_pref is not None,
            input_currency_set=user.input_currency_pref is not None,
        )


class MemberSettingsIn(BaseModel):
    """Send null to return to the household base currency."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"display_currency": "USD"}]}
    )

    display_currency: Currency | None = None
    input_currency: Currency | None = None
