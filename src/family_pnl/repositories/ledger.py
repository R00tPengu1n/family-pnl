"""Database access for the ledger. Every query is scoped to one household (ADR-0004)."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import CategoryKind, OperationType
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

    async def search(
        self, household_id: uuid.UUID, filters: "OperationFilter", *, limit: int, offset: int
    ) -> tuple[list[Operation], int]:
        """A page of operations, newest first, and the number of all that match."""
        query = _filtered(select(Operation), household_id, filters)
        total = await self._session.scalar(
            _filtered(select(func.count(Operation.id)), household_id, filters)
        )
        page = await self._session.scalars(
            query.order_by(
                Operation.operation_date.desc(), Operation.created_at.desc(), Operation.id
            )
            .limit(limit)
            .offset(offset)
        )
        return list(page), total or 0


@dataclass(frozen=True, slots=True)
class OperationFilter:
    date_from: date | None = None
    date_to: date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None  # either side of a transfer counts
    author_id: uuid.UUID | None = None
    currency: Currency | None = None
    type: OperationType | None = None


def _filtered[T](query: Select[T], household_id: uuid.UUID, f: OperationFilter) -> Select[T]:
    query = query.where(Operation.household_id == household_id)
    if f.date_from is not None:
        query = query.where(Operation.operation_date >= f.date_from)
    if f.date_to is not None:
        query = query.where(Operation.operation_date <= f.date_to)
    if f.category_id is not None:
        query = query.where(Operation.category_id == f.category_id)
    if f.account_id is not None:
        query = query.where(
            or_(Operation.account_id == f.account_id, Operation.target_account_id == f.account_id)
        )
    if f.author_id is not None:
        query = query.where(Operation.author_id == f.author_id)
    if f.currency is not None:
        query = query.where(Operation.currency == f.currency)
    if f.type is not None:
        query = query.where(Operation.type == f.type)
    return query


@dataclass(frozen=True, slots=True)
class FlowSum:
    """A signed sum of operations on one account, in one currency, on one date."""

    account_id: uuid.UUID
    currency: Currency
    operation_date: date
    amount: Decimal


class BalanceRepository:
    """Money flows per account, summed in the database (ADR-0004 scoping applies)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flows(self, household_id: uuid.UUID) -> list[FlowSum]:
        """Incomes (+) and expenses (-) per account, currency and date; transfers in and out."""
        sign = func.sum(
            case(
                (Operation.type == OperationType.EXPENSE, -Operation.amount), else_=Operation.amount
            )
        )
        own = await self._session.execute(
            select(Operation.account_id, Operation.currency, Operation.operation_date, sign)
            .where(
                Operation.household_id == household_id,
                Operation.type.in_([OperationType.INCOME, OperationType.EXPENSE]),
            )
            .group_by(Operation.account_id, Operation.currency, Operation.operation_date)
        )
        sent = await self._session.execute(
            select(
                Operation.account_id,
                Operation.currency,
                Operation.operation_date,
                -func.sum(Operation.amount),
            )
            .where(Operation.household_id == household_id, Operation.type == OperationType.TRANSFER)
            .group_by(Operation.account_id, Operation.currency, Operation.operation_date)
        )
        received = await self._session.execute(
            select(
                Operation.target_account_id,
                Operation.target_currency,
                Operation.operation_date,
                func.sum(Operation.target_amount),
            )
            .where(Operation.household_id == household_id, Operation.type == OperationType.TRANSFER)
            .group_by(
                Operation.target_account_id, Operation.target_currency, Operation.operation_date
            )
        )
        return [FlowSum(*row) for result in (own, sent, received) for row in result]
