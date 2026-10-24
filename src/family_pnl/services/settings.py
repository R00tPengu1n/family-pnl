"""Household settings (owner only) and per-member currency preferences."""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.currency import Currency
from family_pnl.domain.permissions import require_owner
from family_pnl.models import Household, User
from family_pnl.services.auth import CurrentUser


@dataclass(frozen=True, slots=True)
class HouseholdChanges:
    name: str | None = None
    base_currency: Currency | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class MemberChanges:
    """Only the fields present are changed; None returns to the household default."""

    fields: dict[str, Currency | None] = field(default_factory=dict)


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def household(self, user: CurrentUser) -> Household:
        return await self._session.get_one(Household, user.household_id)

    async def update_household(self, user: CurrentUser, changes: HouseholdChanges) -> Household:
        require_owner(user.role, "change household settings")
        household = await self.household(user)
        if changes.name is not None:
            household.name = changes.name
        if changes.base_currency is not None:
            household.base_currency = changes.base_currency
        if changes.timezone is not None:
            household.timezone = changes.timezone
        await self._session.commit()
        return household

    async def update_member(self, user: CurrentUser, changes: MemberChanges) -> User:
        member = await self._session.get_one(User, user.id)
        for name in ("display_currency", "input_currency"):
            if name in changes.fields:
                setattr(member, name, changes.fields[name])
        await self._session.commit()
        return member
