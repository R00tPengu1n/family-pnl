"""Database access for users, households and refresh tokens."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.models import Household, Membership, RefreshToken, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    def add(self, user: User) -> None:
        self._session.add(user)


class HouseholdRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, household: Household) -> None:
        self._session.add(household)

    def add_member(self, membership: Membership) -> None:
        self._session.add(membership)

    async def get_membership(self, user_id: uuid.UUID) -> tuple[Membership, Household] | None:
        row = (
            await self._session.execute(
                select(Membership, Household)
                .join(Household, Household.id == Membership.household_id)
                .where(Membership.user_id == user_id)
            )
        ).one_or_none()
        return None if row is None else (row[0], row[1])


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: RefreshToken) -> None:
        self._session.add(token)

    async def get_for_update(self, token_hash: str) -> RefreshToken | None:
        """Lock the row: two concurrent refreshes of one token are serialised."""
        return await self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
