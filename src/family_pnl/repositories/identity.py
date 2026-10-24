"""Database access for users, households and refresh tokens."""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.models import (
    Account,
    Household,
    Invite,
    Membership,
    RefreshToken,
    TelegramLinkCode,
    User,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self._session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def lock(self, user_id: uuid.UUID) -> User:
        result = await self._session.scalars(
            select(User).where(User.id == user_id).with_for_update()
        )
        return result.one()

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

    async def count_members(self, household_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.household_id == household_id)
        )
        return count or 0

    async def list_members(self, household_id: uuid.UUID) -> list[tuple[Membership, User]]:
        rows = await self._session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.household_id == household_id)
            .order_by(Membership.joined_at, User.email)
        )
        return [(row[0], row[1]) for row in rows]

    async def lock_membership(self, user_id: uuid.UUID) -> Membership:
        """The membership of an authenticated user, locked for a move between households."""
        result = await self._session.scalars(
            select(Membership).where(Membership.user_id == user_id).with_for_update()
        )
        return result.one()

    async def has_accounts(self, household_id: uuid.UUID) -> bool:
        found = await self._session.scalar(
            select(Account.id).where(Account.household_id == household_id).limit(1)
        )
        return found is not None

    async def delete(self, household_id: uuid.UUID) -> None:
        await self._session.execute(delete(Household).where(Household.id == household_id))


class InviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, invite: Invite) -> None:
        self._session.add(invite)

    async def get_for_update(self, code_hash: str) -> Invite | None:
        """Lock the row: one code cannot be redeemed twice concurrently."""
        return await self._session.scalar(
            select(Invite).where(Invite.code_hash == code_hash).with_for_update()
        )


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


class TelegramLinkCodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, code: TelegramLinkCode) -> None:
        self._session.add(code)

    async def get_for_update(self, code_hash: str) -> TelegramLinkCode | None:
        return await self._session.scalar(
            select(TelegramLinkCode)
            .where(TelegramLinkCode.code_hash == code_hash)
            .with_for_update()
        )
