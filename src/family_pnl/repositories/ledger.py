"""Database access for the ledger. Every query is scoped to one household (ADR-0004)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.models import Account


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, account: Account) -> None:
        self._session.add(account)

    async def get(self, household_id: uuid.UUID, account_id: uuid.UUID) -> Account | None:
        return await self._session.scalar(
            select(Account).where(Account.household_id == household_id, Account.id == account_id)
        )

    async def list(self, household_id: uuid.UUID, *, include_archived: bool) -> list[Account]:
        query = select(Account).where(Account.household_id == household_id)
        if not include_archived:
            query = query.where(Account.archived.is_(False))
        return list(await self._session.scalars(query.order_by(Account.name, Account.id)))
