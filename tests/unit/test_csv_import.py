"""CSV rows of operations: parsed into rows or reported cell by cell."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import CategoryKind, OperationType
from family_pnl.services.csv_import import (
    MAX_BYTES,
    MAX_ROWS,
    AccountRef,
    CategoryRef,
    ImportRow,
    InvalidImportFileError,
    ParsedImport,
    RowError,
    parse_operations,
)

CARD = AccountRef(uuid.uuid4(), Currency.BYN, archived=False)
OLD_CARD = AccountRef(uuid.uuid4(), Currency.BYN, archived=True)
TWIN_A = AccountRef(uuid.uuid4(), Currency.USD, archived=False)
TWIN_B = AccountRef(uuid.uuid4(), Currency.RUB, archived=False)
ACCOUNTS = {"card": [CARD], "old card": [OLD_CARD], "twin": [TWIN_A, TWIN_B]}

FOOD = CategoryRef(uuid.uuid4(), archived=False)
SALARY = CategoryRef(uuid.uuid4(), archived=False)
GONE = CategoryRef(uuid.uuid4(), archived=True)
CATEGORIES = {
    (CategoryKind.EXPENSE, "продукты"): FOOD,
    (CategoryKind.INCOME, "зарплата"): SALARY,
    (CategoryKind.EXPENSE, "старое"): GONE,
}

HEADER = "date,type,amount,account,category,currency,comment"


def parse(text: str) -> ParsedImport:
    return parse_operations(text.encode("utf-8"), ACCOUNTS, CATEGORIES)


def one_row(**cells: str) -> str:
    values = {
        "date": "2026-10-20",
        "type": "expense",
        "amount": "12.50",
        "account": "Card",
        "category": "Продукты",
        "currency": "",
        "comment": "",
        **cells,
    }
    return HEADER + "\n" + ",".join(values[c] for c in HEADER.split(","))


def errors_of(text: str) -> list[tuple[int, str, str]]:
    return [(e.row, e.column, e.reason) for e in parse(text).errors]


def test_a_valid_row_becomes_an_operation() -> None:
    parsed = parse(one_row(comment="Молоко", currency="usd"))

    assert parsed.errors == []
    assert parsed.rows == [
        ImportRow(
            row=2,
            type=OperationType.EXPENSE,
            operation_date=date(2026, 10, 20),
            amount=Decimal("12.50"),
            currency=Currency.USD,
            account_id=CARD.id,
            category_id=FOOD.id,
            comment="Молоко",
        )
    ]


def test_without_a_currency_the_account_currency_is_used() -> None:
    row = parse(one_row(amount="5")).rows[0]

    assert (row.currency, row.amount, row.comment) == (Currency.BYN, Decimal("5.00"), None)


def test_names_are_matched_ignoring_case_and_spaces() -> None:
    parsed = parse(one_row(type=" Income ", account="  CARD ", category="ЗАРПЛАТА"))

    assert parsed.errors == []
    assert (parsed.rows[0].type, parsed.rows[0].category_id) == (OperationType.INCOME, SALARY.id)


def test_semicolons_a_bom_and_any_column_order_are_accepted() -> None:
    food = "Продукты"
    text = f"Category;Amount;Account;Type;Date\n{food};7.10;Card;expense;2026-10-01\n"

    parsed = parse_operations(b"\xef\xbb\xbf" + text.encode("utf-8"), ACCOUNTS, CATEGORIES)

    assert parsed.errors == []
    assert (parsed.rows[0].amount, parsed.rows[0].operation_date) == (
        Decimal("7.10"),
        date(2026, 10, 1),
    )


def test_quoted_cells_may_hold_the_separator() -> None:
    parsed = parse(one_row(comment='"Хлеб, молоко"'))

    assert parsed.rows[0].comment == "Хлеб, молоко"


@pytest.mark.parametrize(
    ("cells", "column", "reason"),
    [
        ({"date": ""}, "date", "Required"),
        ({"date": "20.10.2026"}, "date", "Not a date in the form YYYY-MM-DD"),
        ({"date": "20261020"}, "date", "Not a date in the form YYYY-MM-DD"),
        ({"date": "2026-02-30"}, "date", "Not a date in the form YYYY-MM-DD"),
        ({"date": "1999-12-31"}, "date", "Outside 2000-01-01 to 2099-12-31"),
        ({"date": "2100-01-01"}, "date", "Outside 2000-01-01 to 2099-12-31"),
        ({"type": ""}, "type", "Required"),
        ({"type": "transfer"}, "type", "Must be income or expense"),
        ({"amount": ""}, "amount", "Required"),
        ({"amount": '"12,50"'}, "amount", "Not a number; use a point before the decimals"),
        ({"amount": "1e3"}, "amount", "Not a number; use a point before the decimals"),
        ({"amount": "Infinity"}, "amount", "Not a number; use a point before the decimals"),
        ({"amount": "0"}, "amount", "Must be positive and below one trillion"),
        ({"amount": "-5"}, "amount", "Must be positive and below one trillion"),
        ({"amount": "1000000000000"}, "amount", "Must be positive and below one trillion"),
        ({"amount": "1.005"}, "amount", "At most two decimals"),
        ({"account": ""}, "account", "Required"),
        ({"account": "Wallet"}, "account", "No account named 'Wallet'"),
        ({"account": "Old card"}, "account", "The account is archived"),
        ({"account": "Twin"}, "account", "Several accounts are named 'Twin'"),
        ({"currency": "EUR"}, "currency", "Must be RUB, BYN or USD"),
        ({"category": ""}, "category", "Required"),
        ({"category": "Кино"}, "category", "No expense category named 'Кино'"),
        ({"category": "Зарплата"}, "category", "No expense category named 'Зарплата'"),
        ({"category": "Старое"}, "category", "The category is archived"),
        ({"comment": "x" * 501}, "comment", "Longer than 500 characters"),
    ],
)
def test_a_bad_cell_is_reported_with_row_column_and_reason(
    cells: dict[str, str], column: str, reason: str
) -> None:
    parsed = parse(one_row(**cells))

    assert parsed.rows == []
    assert parsed.errors == [RowError(2, column, reason)]


def test_the_largest_amount_and_the_longest_comment_still_fit() -> None:
    parsed = parse(one_row(amount="999999999999.99", comment="x" * 500))

    assert parsed.errors == []


def test_every_bad_cell_of_a_row_is_reported() -> None:
    found = errors_of(one_row(date="yesterday", amount="0", account="Wallet"))

    assert [column for _, column, _ in found] == ["date", "amount", "account"]


def test_an_unknown_type_skips_the_category_check() -> None:
    assert [column for _, column, _ in errors_of(one_row(type="gift"))] == ["type"]


def test_rows_are_numbered_as_in_a_spreadsheet_counting_blank_lines() -> None:
    good = "2026-10-20,expense,1,Card,Продукты,,"
    text = f"{HEADER}\n{good}\n\n2026-10-20,expense,0,Card,Продукты,,\n{good}\n\n"

    parsed = parse(text)

    assert [row.row for row in parsed.rows] == [2, 5]
    assert [e.row for e in parsed.errors] == [4]


def test_a_row_with_the_wrong_number_of_cells_is_one_error() -> None:
    assert errors_of(HEADER + "\n2026-10-20,expense,1") == [(2, "", "Expected 7 cells, found 3")]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\xff\xfe" + HEADER.encode("utf-16-le"), "The file is not UTF-8"),
        (b"", "The file has no header row"),
        (b"\n2026-10-20,expense", "The file has no header row"),
        ((HEADER + ",color").encode(), "Unknown columns: color"),
        (b"date,type,amount,account,category,date", "A column appears twice"),
        (b"date,type,amount", "Missing columns: account, category"),
    ],
    ids=["utf-16", "empty", "blank-header", "unknown", "twice", "missing"],
)
def test_a_file_that_cannot_be_read_is_rejected_as_a_whole(content: bytes, message: str) -> None:
    with pytest.raises(InvalidImportFileError) as raised:
        parse_operations(content, ACCOUNTS, CATEGORIES)

    assert str(raised.value) == message


def test_the_file_size_is_limited() -> None:
    content = (HEADER + "\n").encode() + b" " * MAX_BYTES

    with pytest.raises(InvalidImportFileError) as raised:
        parse_operations(content, ACCOUNTS, CATEGORIES)

    assert str(raised.value) == f"The file is larger than {MAX_BYTES} bytes"


def test_the_number_of_rows_is_limited() -> None:
    row = "\n2026-10-20,expense,1,Card,Продукты,,"

    assert len(parse(HEADER + row * MAX_ROWS).rows) == MAX_ROWS
    with pytest.raises(InvalidImportFileError) as raised:
        parse(HEADER + row * (MAX_ROWS + 1))
    assert str(raised.value) == f"The file has more than {MAX_ROWS} rows"


@pytest.mark.parametrize("day", ["2000-01-01", "2099-12-31"])
def test_the_first_and_last_accepted_dates_import(day: str) -> None:
    assert parse(one_row(date=day)).errors == []
