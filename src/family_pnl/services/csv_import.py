"""CSV import of incomes and expenses, with an error for every bad cell.

Format: UTF-8 (a BOM is fine), comma or semicolon separated, a header row with these
columns in any order (names are case-insensitive):

    date      YYYY-MM-DD                                   required
    type      income | expense                             required
    amount    positive, a point before at most two decimals required
    account   account name, as in the app                  required
    category  category name of the same kind as the type   required
    currency  RUB | BYN | USD; empty means the account's   optional
    comment   up to 500 characters                         optional

Rows are numbered as in a spreadsheet: the header is row 1. Accounts and categories are
matched by name ignoring case and surrounding spaces; an unknown or archived one is an
error, never created on the fly. Transfers are not imported.

Strict mode (the default) imports nothing if any row is wrong; otherwise the valid rows are
imported and the wrong ones reported. A dry run checks everything and imports nothing.
"""

import csv
import io
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import ValidationFailedError
from family_pnl.domain.budgets import first_of_month
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import (
    EARLIEST_DATE,
    LATEST_DATE,
    CategoryKind,
    OperationType,
    category_key,
)
from family_pnl.domain.money import CENT
from family_pnl.models import Operation
from family_pnl.repositories.ledger import (
    AccountRepository,
    CategoryRepository,
    OperationRepository,
)
from family_pnl.services.auth import CurrentUser
from family_pnl.services.budget_execution import BudgetExecutionService

MAX_BYTES = 1024 * 1024
MAX_ROWS = 5000
MAX_COMMENT = 500
MAX_AMOUNT = Decimal("999999999999.99")  # NUMERIC(14, 2)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

REQUIRED = ("date", "type", "amount", "account", "category")
OPTIONAL = ("currency", "comment")


class InvalidImportFileError(ValidationFailedError):
    """The file as a whole cannot be read; no row is looked at."""

    code = "invalid_import_file"


@dataclass(frozen=True, slots=True)
class AccountRef:
    id: uuid.UUID
    currency: Currency
    archived: bool


@dataclass(frozen=True, slots=True)
class CategoryRef:
    id: uuid.UUID
    archived: bool


@dataclass(frozen=True, slots=True)
class RowError:
    row: int
    column: str
    reason: str


@dataclass(frozen=True, slots=True)
class ImportRow:
    row: int
    type: OperationType
    operation_date: date
    amount: Decimal
    currency: Currency
    account_id: uuid.UUID
    category_id: uuid.UUID
    comment: str | None


@dataclass(slots=True)
class ParsedImport:
    rows: list[ImportRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImportResult:
    dry_run: bool
    strict: bool
    total_rows: int
    valid_rows: int
    imported: int
    errors: list[RowError]


def parse_operations(
    content: bytes,
    accounts: Mapping[str, list[AccountRef]],
    categories: Mapping[tuple[CategoryKind, str], CategoryRef],
) -> ParsedImport:
    """Every row checked; accounts are keyed by `category_key(name)`, categories by kind too."""
    if len(content) > MAX_BYTES:
        raise InvalidImportFileError(f"The file is larger than {MAX_BYTES} bytes")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidImportFileError("The file is not UTF-8") from error
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise InvalidImportFileError("The file has no header row")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = [name.strip().lower() for name in next(reader)]
    _check_header(header)
    parsed = ParsedImport()
    data_rows = 0
    for number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue  # blank lines, often at the end of a file
        data_rows += 1
        if data_rows > MAX_ROWS:
            raise InvalidImportFileError(f"The file has more than {MAX_ROWS} rows")
        if len(cells) != len(header):
            parsed.errors.append(
                RowError(number, "", f"Expected {len(header)} cells, found {len(cells)}")
            )
            continue
        _RowParser(number, dict(zip(header, cells, strict=True)), accounts, categories).into(parsed)
    return parsed


def _check_header(header: list[str]) -> None:
    unknown = [name for name in header if name not in REQUIRED + OPTIONAL]
    if unknown:
        raise InvalidImportFileError(f"Unknown columns: {', '.join(unknown)}")
    if len(set(header)) != len(header):
        raise InvalidImportFileError("A column appears twice")
    missing = [name for name in REQUIRED if name not in header]
    if missing:
        raise InvalidImportFileError(f"Missing columns: {', '.join(missing)}")


def _rows_with_errors(parsed: ParsedImport) -> int:
    return len({error.row for error in parsed.errors})


class _RowParser:
    """One row: collects an error per bad cell instead of stopping at the first."""

    def __init__(
        self,
        number: int,
        cells: dict[str, str],
        accounts: Mapping[str, list[AccountRef]],
        categories: Mapping[tuple[CategoryKind, str], CategoryRef],
    ) -> None:
        self._number = number
        self._cells = {name: value.strip() for name, value in cells.items()}
        self._accounts = accounts
        self._categories = categories
        self._errors: list[RowError] = []

    def into(self, parsed: ParsedImport) -> None:
        operation_date = self._date()
        op_type = self._type()
        amount = self._amount()
        account = self._account()
        currency = self._currency(account)
        category = self._category(op_type)
        comment = self._comment()
        if (
            self._errors
            or operation_date is None
            or op_type is None
            or amount is None
            or currency is None
            or account is None
            or category is None
        ):
            parsed.errors.extend(self._errors)  # a cell that is None has reported an error
            return
        parsed.rows.append(
            ImportRow(
                row=self._number,
                type=op_type,
                operation_date=operation_date,
                amount=amount,
                currency=currency,
                account_id=account.id,
                category_id=category.id,
                comment=comment,
            )
        )

    def _fail(self, column: str, reason: str) -> None:
        self._errors.append(RowError(self._number, column, reason))

    def _required(self, column: str) -> str | None:
        value = self._cells[column]
        if not value:
            self._fail(column, "Required")
            return None
        return value

    def _date(self) -> date | None:
        value = self._required("date")
        if value is None:
            return None
        day = _iso_date(value)
        if day is None:
            self._fail("date", "Not a date in the form YYYY-MM-DD")
        elif not EARLIEST_DATE <= day <= LATEST_DATE:
            self._fail("date", "Outside 2000-01-01 to 2099-12-31")
        else:
            return day
        return None

    def _type(self) -> OperationType | None:
        value = self._required("type")
        if value is None:
            return None
        if value.lower() not in (OperationType.INCOME, OperationType.EXPENSE):
            self._fail("type", "Must be income or expense")
            return None
        return OperationType(value.lower())

    def _amount(self) -> Decimal | None:
        value = self._required("amount")
        if value is None:
            return None
        try:
            amount = Decimal(value)
        except InvalidOperation:
            amount = Decimal("NaN")
        if not amount.is_finite() or "e" in value.lower():
            self._fail("amount", "Not a number; use a point before the decimals")
        elif amount <= 0 or amount > MAX_AMOUNT:
            self._fail("amount", "Must be positive and below one trillion")
        elif amount != amount.quantize(CENT):
            self._fail("amount", "At most two decimals")
        else:
            return amount.quantize(CENT)
        return None

    def _account(self) -> AccountRef | None:
        value = self._required("account")
        if value is None:
            return None
        found = self._accounts.get(category_key(value), [])
        usable = [account for account in found if not account.archived]
        if not found:
            self._fail("account", f"No account named {value!r}")
        elif not usable:
            self._fail("account", "The account is archived")
        elif len(usable) > 1:
            self._fail("account", f"Several accounts are named {value!r}")
        else:
            return usable[0]
        return None

    def _currency(self, account: AccountRef | None) -> Currency | None:
        value = self._cells.get("currency", "")
        if not value:
            return None if account is None else account.currency
        try:
            return Currency.parse(value)
        except ValueError:
            self._fail("currency", "Must be RUB, BYN or USD")
            return None

    def _category(self, op_type: OperationType | None) -> CategoryRef | None:
        value = self._required("category")
        if value is None or op_type is None:
            return None
        found = self._categories.get((CategoryKind(op_type.value), category_key(value)))
        if found is None:
            self._fail("category", f"No {op_type.value} category named {value!r}")
        elif found.archived:
            self._fail("category", "The category is archived")
        else:
            return found
        return None

    def _comment(self) -> str | None:
        value = self._cells.get("comment", "")
        if len(value) > MAX_COMMENT:
            self._fail("comment", f"Longer than {MAX_COMMENT} characters")
            return None
        return value or None


def _iso_date(value: str) -> date | None:
    if not _ISO_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None  # the form is right, the day is not: 2026-02-30


class CsvImportService:
    def __init__(
        self, session: AsyncSession, clock: Clock, budgets: BudgetExecutionService
    ) -> None:
        self._session = session
        self._clock = clock
        self._accounts = AccountRepository(session)
        self._categories = CategoryRepository(session)
        self._operations = OperationRepository(session)
        self._budgets = budgets

    async def import_csv(
        self, user: CurrentUser, content: bytes, *, dry_run: bool, strict: bool
    ) -> ImportResult:
        parsed = parse_operations(content, *await self._lookups(user))
        total = len(parsed.rows) + _rows_with_errors(parsed)
        write = not dry_run and not (strict and parsed.errors)
        if write and parsed.rows:
            await self._write(user, parsed.rows)
        return ImportResult(
            dry_run=dry_run,
            strict=strict,
            total_rows=total,
            valid_rows=len(parsed.rows),
            imported=len(parsed.rows) if write else 0,
            errors=parsed.errors,
        )

    async def _lookups(
        self, user: CurrentUser
    ) -> tuple[dict[str, list[AccountRef]], dict[tuple[CategoryKind, str], CategoryRef]]:
        accounts: dict[str, list[AccountRef]] = {}
        for account in await self._accounts.list(user.household_id, include_archived=True):
            accounts.setdefault(category_key(account.name), []).append(
                AccountRef(account.id, account.currency, account.archived)
            )
        categories = {
            (c.kind, c.name_key): CategoryRef(c.id, c.archived)
            for c in await self._categories.list(
                user.household_id, kind=None, include_archived=True
            )
        }
        return accounts, categories

    async def _write(self, user: CurrentUser, rows: list[ImportRow]) -> None:
        now = self._clock.now()
        for row in rows:
            self._operations.add(
                Operation(
                    id=uuid.uuid4(),
                    household_id=user.household_id,
                    type=row.type,
                    amount=row.amount,
                    currency=row.currency,
                    operation_date=row.operation_date,
                    account_id=row.account_id,
                    category_id=row.category_id,
                    comment=row.comment,
                    author_id=user.id,
                    created_at=now,
                    updated_at=now,
                )
            )
        await self._session.flush()  # the budget sums must include the new rows
        checked = {
            (row.category_id, first_of_month(row.operation_date)): row.operation_date
            for row in rows
            if row.type is OperationType.EXPENSE
        }
        for (category_id, _), day in checked.items():
            await self._budgets.check_thresholds(user.household_id, category_id, day)
        await self._session.commit()
