import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import AccountType
from family_pnl.models import Account
from family_pnl.services.balances import AccountBalance

AccountName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AccountCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"name": "Anna card", "type": "card", "currency": "BYN", "shared": False}]
        }
    )

    name: AccountName
    type: AccountType
    currency: Currency
    shared: bool = False


class AccountUpdate(BaseModel):
    """Fields to change; the currency is fixed once the account exists."""

    model_config = ConfigDict(extra="forbid")

    name: AccountName | None = None
    type: AccountType | None = None
    archived: bool | None = None


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    type: AccountType
    currency: Currency
    shared: bool
    holder_id: uuid.UUID | None
    archived: bool
    created_at: datetime

    @classmethod
    def of(cls, account: Account) -> "AccountOut":
        return cls(
            id=account.id,
            name=account.name,
            type=account.type,
            currency=account.currency,
            shared=account.holder_id is None,
            holder_id=account.holder_id,
            archived=account.archived,
            created_at=account.created_at,
        )


class AccountBalanceOut(BaseModel):
    account_id: uuid.UUID
    name: str
    currency: Currency
    balance: Decimal

    @classmethod
    def of(cls, item: AccountBalance) -> "AccountBalanceOut":
        return cls(
            account_id=item.account.id,
            name=item.account.name,
            currency=item.account.currency,
            balance=item.balance.amount,
        )
