"""Database access for the ledger. Every query is scoped to one household (ADR-0004)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.ledger import CategoryKind
from family_pnl.models import Account, Category, Operation


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


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_all(self, categories: list[Category]) -> None:
        self._session.add_all(categories)

    async def get(self, household_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        return await self._session.scalar(
            select(Category).where(
                Category.household_id == household_id, Category.id == category_id
            )
        )

    async def name_taken(self, household_id: uuid.UUID, kind: CategoryKind, name_key: str) -> bool:
        found = await self._session.scalar(
            select(Category.id).where(
                Category.household_id == household_id,
                Category.kind == kind,
                Category.name_key == name_key,
            )
        )
        return found is not None

    async def list(
        self, household_id: uuid.UUID, *, kind: CategoryKind | None, include_archived: bool
    ) -> list[Category]:
        query = select(Category).where(Category.household_id == household_id)
        if kind is not None:
            query = query.where(Category.kind == kind)
        if not include_archived:
            query = query.where(Category.archived.is_(False))
        return list(await self._session.scalars(query.order_by(Category.kind, Category.name)))


class OperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, operation: Operation) -> None:
        self._session.add(operation)

    async def get(self, household_id: uuid.UUID, operation_id: uuid.UUID) -> Operation | None:
        return await self._session.scalar(
            select(Operation).where(
                Operation.household_id == household_id, Operation.id == operation_id
            )
        )

    async def delete(self, operation: Operation) -> None:
        await self._session.delete(operation)
