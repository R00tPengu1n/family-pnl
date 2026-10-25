import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from family_pnl.api.schemas.common import Day
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import OperationType
from family_pnl.models import Operation
from family_pnl.services.csv_import import ImportResult

# NUMERIC(14, 2): positive, at most two decimals and twelve digits before the point.
Amount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]


def _blank_is_none(value: str | None) -> str | None:
    return value or None


# Stripped; a comment of only spaces is stored as no comment.
Comment = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=500),
    AfterValidator(_blank_is_none),
]


class OperationCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
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
        },
    )

    type: OperationType
    amount: Amount = Field(description="For a transfer: in the source account currency")
    account_id: uuid.UUID = Field(description="For a transfer: the source account")
    currency: Currency | None = Field(
        default=None, description="Required for income and expense; a transfer uses the account's"
    )
    category_id: uuid.UUID | None = Field(default=None, description="Not for transfers")
    target_account_id: uuid.UUID | None = Field(default=None, description="Transfers only")
    target_amount: Amount | None = Field(
        default=None,
        description="Transfers between currencies; converted at the date's rate if omitted",
    )
    operation_date: Day | None = Field(
        default=None, description="Defaults to today in the household time zone"
    )
    comment: Comment = None


class OperationUpdate(BaseModel):
    """Fields to change; the type is fixed once the operation exists."""

    model_config = ConfigDict(extra="forbid")

    amount: Amount | None = None
    currency: Currency | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    target_amount: Amount | None = None
    operation_date: Day | None = None
    comment: Comment = None


class OperationOut(BaseModel):
    id: uuid.UUID
    type: OperationType
    amount: Decimal
    currency: Currency
    operation_date: date
    account_id: uuid.UUID
    category_id: uuid.UUID | None
    target_account_id: uuid.UUID | None
    target_amount: Decimal | None
    target_currency: Currency | None
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
            target_account_id=operation.target_account_id,
            target_amount=operation.target_amount,
            target_currency=operation.target_currency,
            comment=operation.comment,
            author_id=operation.author_id,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
        )


class OperationPage(BaseModel):
    items: list[OperationOut]
    total: int = Field(description="All operations matching the filters")
    limit: int
    offset: int


class ImportErrorOut(BaseModel):
    row: int = Field(description="As in a spreadsheet: the header is row 1")
    column: str = Field(description="Empty when the whole row is wrong")
    reason: str


class ImportResultOut(BaseModel):
    dry_run: bool
    strict: bool
    total_rows: int
    valid_rows: int
    imported: int
    errors: list[ImportErrorOut]

    @classmethod
    def of(cls, result: ImportResult) -> "ImportResultOut":
        return cls(
            dry_run=result.dry_run,
            strict=result.strict,
            total_rows=result.total_rows,
            valid_rows=result.valid_rows,
            imported=result.imported,
            errors=[
                ImportErrorOut(row=e.row, column=e.column, reason=e.reason) for e in result.errors
            ],
        )
