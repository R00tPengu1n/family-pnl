"""Household membership: invites, joining a household and the members list."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.security import hash_invite_code, new_invite_code
from family_pnl.domain.identity import Role
from family_pnl.domain.permissions import (
    INVITE_LIFETIME,
    InviteInvalidError,
    check_can_join,
    check_invite_usable,
    require_owner,
)
from family_pnl.models import Invite
from family_pnl.repositories.identity import HouseholdRepository, InviteRepository
from family_pnl.services.auth import CurrentUser


@dataclass(frozen=True, slots=True)
class IssuedInvite:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Member:
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: Role
    joined_at: datetime


class HouseholdService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._households = HouseholdRepository(session)
        self._invites = InviteRepository(session)

    async def create_invite(self, user: CurrentUser) -> IssuedInvite:
        require_owner(user.role, "create invites")
        now = self._clock.now()
        code = new_invite_code()
        invite = Invite(
            id=uuid.uuid4(),
            household_id=user.household_id,
            code_hash=hash_invite_code(code),
            created_by=user.id,
            created_at=now,
            expires_at=now + INVITE_LIFETIME,
        )
        self._invites.add(invite)
        await self._session.commit()
        return IssuedInvite(code=code, expires_at=invite.expires_at)

    async def redeem_invite(self, user: CurrentUser, code: str) -> uuid.UUID:
        """Move the user into the invite's household as a member; return that household id.

        The user's previous household had only them in it (checked) and is deleted.
        """
        now = self._clock.now()
        invite = await self._invites.get_for_update(hash_invite_code(code))
        if invite is None:
            raise InviteInvalidError("Invite code is invalid or has expired")
        check_invite_usable(expires_at=invite.expires_at, redeemed_at=invite.redeemed_at, now=now)
        membership = await self._households.lock_membership(user.id)
        previous_household = membership.household_id
        check_can_join(
            current_household_id=previous_household,
            members_in_current=await self._households.count_members(previous_household),
            invite_household_id=invite.household_id,
            has_accounts=await self._households.has_accounts(previous_household),
        )

        membership.household_id = invite.household_id
        membership.role = Role.MEMBER
        membership.joined_at = now
        invite.redeemed_by = user.id
        invite.redeemed_at = now
        # Move the membership first: deleting the old household cascades to its memberships.
        await self._session.flush()
        await self._households.delete(previous_household)
        await self._session.commit()
        return invite.household_id

    async def list_members(self, user: CurrentUser) -> list[Member]:
        rows = await self._households.list_members(user.household_id)
        return [
            Member(
                user_id=u.id,
                email=u.email,
                display_name=u.display_name,
                role=m.role,
                joined_at=m.joined_at,
            )
            for m, u in rows
        ]
