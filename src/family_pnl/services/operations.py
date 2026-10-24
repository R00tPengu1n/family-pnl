"""Incomes, expenses and transfers: recorded, edited and deleted by their author or the owner.

Income and expense: an account, a category of the same kind, an amount in any currency.
Transfer: from one account to another, no category; the amount is in the source account's
currency, the target amount in the target account's. When the currencies differ and no
target amount is given, it is converted at the official rate of the operation date and
rounded once.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import NotFoundError, ValidationFailedError
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import (
    OperationType,
    check_category_fits,
    check_transfer_accounts,
    require_operation_editor,
)
from family_pnl.domain.money import CENT, Money
from family_pnl.models import Account, Category, Operation
from family_pnl.repositories.ledger import (
    AccountRepository,
    CategoryRepository,
    OperationRepository,
)
from family_pnl.services.auth import CurrentUser
from family_pnl.services.fx import RateService


class OperationNotFoundError(NotFoundError):
    pass


class ArchivedError(ValidationFailedError):
    code = "archived"


class InvalidOperationError(ValidationFailedError):
    """Fields that do not fit the operation type."""

    code = "invalid_operation"


@dataclass(frozen=True, slots=True)
class NewOperation:
    type: OperationType
    amount: Decimal
    account_id: uuid.UUID
    currency: Currency | None = None
    category_id: uuid.UUID | None = None
    target_account_id: uuid.UUID | None = None
    target_amount: Decimal | None = None
    operation_date: date | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class OperationChanges:
    amount: Decimal | None = None
    currency: Currency | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    target_amount: Decimal | None = None
    operation_date: date | None = None
    comment: str | None = None


class OperationService:
    def __init__(self, session: AsyncSession, clock: Clock, rates: RateService) -> None:
        self._session = session
        self._clock = clock
        self._rates = rates
        self._operations = OperationRepository(session)
        self._accounts = AccountRepository(session)
        self._categories = CategoryRepository(session)

    async def create(self, user: CurrentUser, new: NewOperation) -> Operation:
        source = await self._usable_account(user, new.account_id)
        now = self._clock.now()
        operation = Operation(
            id=uuid.uuid4(),
            household_id=user.household_id,
            type=new.type,
            amount=new.amount.quantize(CENT),  # as stored: NUMERIC(14, 2)
            operation_date=new.operation_date or self._today(user),
            account_id=source.id,
            comment=new.comment,
            author_id=user.id,
            created_at=now,
            updated_at=now,
        )
        if new.type is OperationType.TRANSFER:
            await self._fill_transfer(user, operation, source, new)
        else:
            await self._fill_income_or_expense(user, operation, new)
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
        # The date first: a transfer between currencies is converted at the new date.
        if changes.operation_date is not None:
            operation.operation_date = changes.operation_date
        if changes.comment is not None:
            operation.comment = changes.comment
        if operation.type is OperationType.TRANSFER:
            await self._update_transfer(operation, changes)
        else:
            await self._update_income_or_expense(user, operation, changes)
        operation.updated_at = self._clock.now()
        await self._session.commit()
        return operation

    async def delete(self, user: CurrentUser, operation_id: uuid.UUID) -> None:
        operation = await self.get(user, operation_id)
        require_operation_editor(actor_id=user.id, role=user.role, author_id=operation.author_id)
        await self._operations.delete(operation)
        await self._session.commit()

    async def _fill_income_or_expense(
        self, user: CurrentUser, operation: Operation, new: NewOperation
    ) -> None:
        if new.target_account_id is not None or new.target_amount is not None:
            raise InvalidOperationError(f"An {new.type} has no target account")
        if new.category_id is None or new.currency is None:
            raise InvalidOperationError(f"An {new.type} needs a category and a currency")
        category = await self._usable_category(user, new.category_id)
        check_category_fits(new.type, category.kind)
        operation.category_id = category.id
        operation.currency = new.currency

    async def _fill_transfer(
        self, user: CurrentUser, operation: Operation, source: Account, new: NewOperation
    ) -> None:
        if new.category_id is not None:
            raise InvalidOperationError("A transfer has no category")
        if new.target_account_id is None:
            raise InvalidOperationError("A transfer needs a target account")
        if new.currency is not None and new.currency is not source.currency:
            raise InvalidOperationError(
                f"A transfer is made in the source account currency ({source.currency})"
            )
        check_transfer_accounts(source.id, new.target_account_id)
        target = await self._usable_account(user, new.target_account_id)
        operation.currency = source.currency
        operation.target_account_id = target.id
        operation.target_currency = target.currency
        operation.target_amount = await self._target_amount(
            operation, target.currency, new.target_amount
        )

    async def _update_income_or_expense(
        self, user: CurrentUser, operation: Operation, changes: OperationChanges
    ) -> None:
        if changes.target_amount is not None:
            raise InvalidOperationError(f"An {operation.type} has no target amount")
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

    async def _update_transfer(self, operation: Operation, changes: OperationChanges) -> None:
        if (
            changes.account_id is not None
            or changes.category_id is not None
            or changes.currency is not None
        ):
            raise InvalidOperationError(
                "The accounts and currencies of a transfer are fixed; delete and record it again"
            )
        if changes.amount is not None:
            operation.amount = changes.amount.quantize(CENT)
        # Set for every transfer: ck_operations_target_iff_transfer.
        target_currency = cast(Currency, operation.target_currency)
        moved_date = (
            changes.operation_date is not None and target_currency is not operation.currency
        )
        if changes.amount is not None or changes.target_amount is not None or moved_date:
            operation.target_amount = await self._target_amount(
                operation, target_currency, changes.target_amount
            )

    async def _target_amount(
        self, operation: Operation, target_currency: Currency, given: Decimal | None
    ) -> Decimal:
        """The target side of a transfer: the same amount, the given one, or converted."""
        if target_currency is operation.currency:
            if given is not None and given.quantize(CENT) != operation.amount:
                raise InvalidOperationError(
                    "A transfer between accounts of one currency moves the same amount"
                )
            return operation.amount
        if given is not None:
            return given.quantize(CENT)
        rates = await self._rates.rates_on(operation.operation_date)
        source = Money(operation.amount, operation.currency)
        return rates.convert(source, target_currency).rounded().amount

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
