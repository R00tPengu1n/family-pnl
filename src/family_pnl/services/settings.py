"""Household settings (owner only) and per-member currency preferences."""

from dataclasses import dataclass
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.currency import Currency
from family_pnl.domain.permissions import require_owner
from family_pnl.models import Household, User
from family_pnl.repositories.identity import HouseholdRepository, UserRepository
from family_pnl.services.auth import CurrentUser


class _Unset(Enum):
    UNSET = "unset"


# A field left out of a change: unlike None, which returns to the household default.
UNSET = _Unset.UNSET


@dataclass(frozen=True, slots=True)
class HouseholdChanges:
    name: str | None = None
    base_currency: Currency | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class MemberChanges:
    """Only the fields given are changed; None returns to the household default."""

    display_currency: Currency | _Unset | None = UNSET
    input_currency: Currency | _Unset | None = UNSET


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._households = HouseholdRepository(session)
        self._users = UserRepository(session)

    async def household(self, user: CurrentUser) -> Household:
        return await self._households.get(user.household_id)

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
        member = await self._users.lock(user.id)
        if changes.display_currency is not UNSET:
            member.display_currency = changes.display_currency
        if changes.input_currency is not UNSET:
            member.input_currency = changes.input_currency
        await self._session.commit()
        return member
