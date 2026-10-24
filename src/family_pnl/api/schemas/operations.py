import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import OperationType
from family_pnl.models import Operation

# NUMERIC(14, 2): positive, at most two decimals and twelve digits before the point.
Amount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class OperationCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "expense",
                    "amount": "12.50",
                    "currency": "BYN",
                    "account_id": "0b8f6a0e-2f5a-4d43-9e86-3d2a0a6c1f11",
                    "category_id": "6f1d1b8a-0c0a-4f0e-8c2b-1a4b8a2e9d22",
                    "operation_date": "2026-10-20",
                    "comment": "Молоко",
                }
            ]
        }
    )

    type: OperationType
    amount: Amount
    currency: Currency
    account_id: uuid.UUID
    category_id: uuid.UUID
    operation_date: date | None = Field(
        default=None, description="Defaults to today in the household time zone"
    )
    comment: Comment | None = None


class OperationUpdate(BaseModel):
    """Fields to change; the type is fixed once the operation exists."""

    model_config = ConfigDict(extra="forbid")

    amount: Amount | None = None
    currency: Currency | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    operation_date: date | None = None
    comment: Comment | None = None


class OperationOut(BaseModel):
    id: uuid.UUID
    type: OperationType
    amount: Decimal
    currency: Currency
    operation_date: date
    account_id: uuid.UUID
    category_id: uuid.UUID
    comment: str | None
    author_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, operation: Operation) -> "OperationOut":
        return cls(
            id=operation.id,
            type=operation.type,
            amount=operation.amount,
            currency=operation.currency,
            operation_date=operation.operation_date,
            account_id=operation.account_id,
            category_id=operation.category_id,
            comment=operation.comment,
            author_id=operation.author_id,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
        )
