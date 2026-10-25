"""CSV export of a period report: the same figures as the JSON report, one per row."""

import csv
import io
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from family_pnl.core.clock import FrozenClock
from tests.integration.helpers import Actor, sign_up
from tests.integration.ledger_helpers import new_account, record
from tests.integration.report_helpers import NOW, PERIOD, build_family, install_rates
from tests.integration.test_rate_service import FakeSource

EXPORT = PERIOD.replace("/reports?", "/reports/export.csv?")
HEADER = ["section", "month", "category", "member", "metric", "amount", "currency"]


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def source(app: FastAPI) -> FakeSource:
    return install_rates(app)


@pytest.fixture
async def family(client: AsyncClient, source: FakeSource) -> dict[str, Any]:
    return await build_family(client)


async def export(client: AsyncClient, actor: Actor, path: str = EXPORT) -> list[list[str]]:
    response = await client.get(path, headers=actor.headers)
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def expected_rows(report: dict[str, Any]) -> list[list[str]]:
    """The JSON report rewritten in the export's long format."""
    currency = report["currency"]
    rows = [HEADER]

    def totals(section: str, values: dict[str, str], month: str = "", member: str = "") -> None:
        for metric in ("income", "expense", "net"):
            rows.append([section, month, "", member, metric, values[metric], currency])

    totals("total", report["totals"])
    for c in report["by_category"]:
        rows.append(["category", "", c["category"], "", c["kind"], c["amount"], currency])
    for m in report["by_member"]:
        totals("member", m["totals"], member=m["name"])
    for m in report["by_month"]:
        totals("month", m["totals"], month=m["month"])
    for p in report["plan_vs_actual"]:
        for metric in ("planned", "actual", "remaining"):
            rows.append(["plan", p["month"], p["category"], "", metric, p[metric], currency])
    return rows


@pytest.mark.parametrize("who", ["anna", "ivan"])
async def test_the_export_matches_the_json_report(
    client: AsyncClient, family: dict[str, Any], who: str
) -> None:
    actor = family[who]
    report = (await client.get(PERIOD, headers=actor.headers)).json()

    assert await export(client, actor) == expected_rows(report)


async def test_amounts_are_plain_decimals(client: AsyncClient, family: dict[str, Any]) -> None:
    rows = await export(client, family["anna"])

    assert rows[1:4] == [
        ["total", "", "", "", "income", "2995.00", "BYN"],
        ["total", "", "", "", "expense", "379.50", "BYN"],
        ["total", "", "", "", "net", "2615.50", "BYN"],
    ]
    assert ["month", "2026-09", "", "", "net", "-50.00", "BYN"] in rows


async def test_the_file_is_an_attachment_named_after_the_period(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.get(EXPORT, headers=anna.headers)

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="report_2026-09-01_2026-10-31.csv"'
    )


@pytest.mark.parametrize("name", ["=HYPERLINK(1)", "+1", "-1", "@SUM(A1)"])
async def test_category_names_cannot_become_formulas(client: AsyncClient, name: str) -> None:
    # A household of its own: amounts in its base currency need no rates.
    anna = await sign_up(client, "anna@example.com")
    created = await client.post(
        "/categories", headers=anna.headers, json={"name": name, "kind": "expense"}
    )
    assert created.status_code == 201, created.text
    card = await new_account(client, anna, "RUB", "Wallet")
    await record(
        client,
        anna,
        type="expense",
        amount="1",
        currency="RUB",
        account_id=card,
        category_id=created.json()["id"],
    )

    rows = await export(client, anna)

    assert ["category", "", f"'{name}", "", "expense", "1.00", "RUB"] in rows


async def test_an_invalid_period_is_rejected_as_in_the_report(client: AsyncClient) -> None:
    anna = await sign_up(client, "anna@example.com")

    response = await client.get(
        "/reports/export.csv?from=2026-10-02&to=2026-10-01", headers=anna.headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_period"


async def test_the_export_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get(EXPORT)).status_code == 401
