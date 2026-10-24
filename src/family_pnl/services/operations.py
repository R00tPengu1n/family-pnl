"""Incomes and expenses: recorded, edited and deleted by their author or the owner."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import NotFoundError, ValidationFailedError
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import OperationType, check_category_fits, require_operation_editor
from family_pnl.domain.money import CENT
from family_pnl.models import Account, Category, Operation
from family_pnl.repositories.ledger import (
    AccountRepository,
    CategoryRepository,
    OperationRepository,
)
from family_pnl.services.auth import CurrentUser


class OperationNotFoundError(NotFoundError):
    pass


class ArchivedError(ValidationFailedError):
    code = "archived"


@dataclass(frozen=True, slots=True)
class NewOperation:
    type: OperationType
    amount: Decimal
    currency: Currency
    account_id: uuid.UUID
    category_id: uuid.UUID
    operation_date: date | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class OperationChanges:
    amount: Decimal | None = None
    currency: Currency | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    operation_date: date | None = None
    comment: str | None = None


class OperationService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._operations = OperationRepository(session)
        self._accounts = AccountRepository(session)
        self._categories = CategoryRepository(session)

    async def create(self, user: CurrentUser, new: NewOperation) -> Operation:
        await self._usable_account(user, new.account_id)
        category = await self._usable_category(user, new.category_id)
        check_category_fits(new.type, category.kind)
        now = self._clock.now()
        operation = Operation(
            id=uuid.uuid4(),
            household_id=user.household_id,
            type=new.type,
            amount=new.amount.quantize(CENT),  # as stored: NUMERIC(14, 2)
            currency=new.currency,
            operation_date=new.operation_date or self._today(user),
            account_id=new.account_id,
            category_id=new.category_id,
            comment=new.comment,
            author_id=user.id,
            created_at=now,
            updated_at=now,
        )
        self._operations.add(operation)
        await self._session.commit()
        return operation

    async def get(self, user: CurrentUser, operation_id: uuid.UUID) -> Operation:
        operation = await self._operations.get(user.household_id, operation_id)
        if operation is None:
            raise OperationNotFoundError("Operation not found")
        return operation

    async def update(
        self, user: CurrentUser, operation_id: uuid.UUID, changes: OperationChanges
    ) -> Operation:
        operation = await self.get(user, operation_id)
        require_operation_editor(actor_id=user.id, role=user.role, author_id=operation.author_id)
        if changes.account_id is not None:
            await self._usable_account(user, changes.account_id)
            operation.account_id = changes.account_id
        if changes.category_id is not None:
            category = await self._usable_category(user, changes.category_id)
            check_category_fits(operation.type, category.kind)
            operation.category_id = changes.category_id
        if changes.amount is not None:
            operation.amount = changes.amount.quantize(CENT)
        if changes.currency is not None:
            operation.currency = changes.currency
        if changes.operation_date is not None:
            operation.operation_date = changes.operation_date
        if changes.comment is not None:
            operation.comment = changes.comment
        operation.updated_at = self._clock.now()
        await self._session.commit()
        return operation

    async def delete(self, user: CurrentUser, operation_id: uuid.UUID) -> None:
        operation = await self.get(user, operation_id)
        require_operation_editor(actor_id=user.id, role=user.role, author_id=operation.author_id)
        await self._operations.delete(operation)
        await self._session.commit()

    async def _usable_account(self, user: CurrentUser, account_id: uuid.UUID) -> Account:
        account = await self._accounts.get(user.household_id, account_id)
        if account is None:
            raise NotFoundError("Account not found")
        if account.archived:
            raise ArchivedError("The account is archived")
        return account

    async def _usable_category(self, user: CurrentUser, category_id: uuid.UUID) -> Category:
        category = await self._categories.get(user.household_id, category_id)
        if category is None:
            raise NotFoundError("Category not found")
        if category.archived:
            raise ArchivedError("The category is archived")
        return category

    def _today(self, user: CurrentUser) -> date:
        return self._clock.now().astimezone(ZoneInfo(user.household_timezone)).date()
