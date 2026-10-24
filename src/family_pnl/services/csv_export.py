"""CSV export of a period report.

One figure per row (long format), so every part of the report fits one table that a
spreadsheet can filter or pivot: `section` says which part the row belongs to and `metric`
which figure it is. The file is UTF-8 with a BOM, which Excel needs to read Cyrillic;
separators follow RFC 4180. Amounts are written from `Decimal` as they are, never through
float. Text a member typed (category names) is guarded against formula injection.
"""

import csv
import io
from decimal import Decimal

from family_pnl.services.reports import Report, Totals

HEADER = ["section", "month", "category", "member", "metric", "amount", "currency"]

# Cells starting with these are run as formulas by spreadsheets (OWASP: CSV injection).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def report_filename(report: Report) -> str:
    return f"report_{report.date_from.isoformat()}_{report.date_to.isoformat()}.csv"


def report_csv(report: Report) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    currency = report.currency.value

    def totals(section: str, values: Totals, month: str = "", member: str = "") -> None:
        for metric, amount in (
            ("income", values.income),
            ("expense", values.expense),
            ("net", values.net),
        ):
            writer.writerow([section, month, "", _text(member), metric, _amount(amount), currency])

    totals("total", report.totals)
    for line in report.by_category:
        writer.writerow(
            [
                "category",
                "",
                _text(line.category),
                "",
                line.kind.value,
                _amount(line.amount),
                currency,
            ]
        )
    for member in report.by_member:
        totals("member", member.totals, member=member.name or "")
    for month in report.by_month:
        totals("month", month.totals, month=month.month.strftime("%Y-%m"))
    for plan in report.plan_vs_actual:
        for metric, amount in (
            ("planned", plan.planned),
            ("actual", plan.actual),
            ("remaining", plan.remaining),
        ):
            writer.writerow(
                [
                    "plan",
                    plan.month.strftime("%Y-%m"),
                    _text(plan.category),
                    "",
                    metric,
                    _amount(amount),
                    currency,
                ]
            )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _amount(value: Decimal) -> str:
    return f"{value:f}"


def _text(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_START) else value
