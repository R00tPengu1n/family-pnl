"""Budget drafts, limits and approval, with the window evaluated on the household date."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response

from family_pnl.core.clock import FrozenClock
from tests.integration.helpers import Actor, assert_hidden_from, join_household, log_in, sign_up
from tests.integration.ledger_helpers import category_id

NOVEMBER = "2026-11"
INSIDE = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)  # the window for November is 20-30 October
OUTSIDE = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FrozenClock:
    """Inside the November window by default; tokens are issued at this time."""
    return FrozenClock(INSIDE)


@pytest.fixture
async def anna(client: AsyncClient) -> Actor:
    return await sign_up(client, "anna@example.com")


@pytest.fixture
async def ivan(client: AsyncClient, anna: Actor) -> Actor:
    return await join_household(client, anna, "ivan@example.com")


async def set_limit(
    client: AsyncClient, actor: Actor, category: str, amount: str, month: str = NOVEMBER
) -> Response:
    return await client.put(
        f"/budgets/{month}/limits/{category}", headers=actor.headers, json={"amount": amount}
    )


async def budget(client: AsyncClient, actor: Actor, month: str = NOVEMBER) -> dict[str, Any]:
    response = await client.get(f"/budgets/{month}", headers=actor.headers)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def test_a_month_without_a_budget_reads_as_an_empty_draft(
    client: AsyncClient, anna: Actor
) -> None:

    found = await budget(client, anna)

    assert found["month"] == NOVEMBER
    assert found["status"] == "draft"
    assert found["currency"] == "RUB"
    assert found["limits"] == []
    assert found["window"] == {"opens": "2026-10-20", "closes": "2026-10-30", "open": True}


async def test_a_member_sets_limits_inside_the_window(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    food = await category_id(client, anna, "Продукты")

    response = await set_limit(client, ivan, food, "800")

    assert response.status_code == 200
    limits = (await budget(client, anna))["limits"]
    assert limits == [{"category_id": food, "category": "Продукты", "amount": "800.00"}]


async def test_setting_a_limit_again_changes_it(client: AsyncClient, anna: Actor) -> None:
    food = await category_id(client, anna, "Продукты")
    await set_limit(client, anna, food, "800")

    await set_limit(client, anna, food, "650.50")

    assert [lim["amount"] for lim in (await budget(client, anna))["limits"]] == ["650.50"]


async def test_a_limit_can_be_removed(client: AsyncClient, anna: Actor) -> None:
    food = await category_id(client, anna, "Продукты")
    await set_limit(client, anna, food, "800")

    response = await client.delete(f"/budgets/{NOVEMBER}/limits/{food}", headers=anna.headers)

    assert response.status_code == 204
    assert (await budget(client, anna))["limits"] == []


async def test_outside_the_window_only_the_owner_changes_the_budget(
    client: AsyncClient, anna: Actor, ivan: Actor, clock: FrozenClock
) -> None:
    food = await category_id(client, anna, "Продукты")
    clock.set(OUTSIDE)
    anna, ivan = await log_in(client, anna.email), await log_in(client, ivan.email)

    by_member = await set_limit(client, ivan, food, "800")
    by_owner = await set_limit(client, anna, food, "800")

    assert by_member.status_code == 403
    assert by_owner.status_code == 200


async def test_only_the_owner_approves(client: AsyncClient, anna: Actor, ivan: Actor) -> None:
    await set_limit(client, ivan, await category_id(client, anna, "Продукты"), "800")

    by_member = await client.post(f"/budgets/{NOVEMBER}/approve", headers=ivan.headers)
    by_owner = await client.post(f"/budgets/{NOVEMBER}/approve", headers=anna.headers)

    assert by_member.status_code == 403
    assert by_owner.status_code == 200
    assert by_owner.json()["status"] == "approved"
    assert by_owner.json()["approved_at"] == INSIDE.isoformat().replace("+00:00", "Z")


async def test_an_approved_budget_is_changed_only_by_the_owner_and_stays_approved(
    client: AsyncClient, anna: Actor, ivan: Actor
) -> None:
    food = await category_id(client, anna, "Продукты")
    await set_limit(client, anna, food, "800")
    await client.post(f"/budgets/{NOVEMBER}/approve", headers=anna.headers)

    by_member = await set_limit(client, ivan, food, "900")
    by_owner = await set_limit(client, anna, food, "900")

    assert by_member.status_code == 403
    assert by_owner.status_code == 200
    assert (await budget(client, anna))["status"] == "approved"


async def test_approving_a_month_without_a_budget_is_not_found(
    client: AsyncClient, anna: Actor
) -> None:

    response = await client.post(f"/budgets/{NOVEMBER}/approve", headers=anna.headers)

    assert response.status_code == 404


async def test_limits_are_for_expense_categories_only(client: AsyncClient, anna: Actor) -> None:
    salary = await category_id(client, anna, "Зарплата")

    response = await set_limit(client, anna, salary, "100")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "category_kind_mismatch"


async def test_the_window_is_judged_on_the_household_date(
    client: AsyncClient, anna: Actor, ivan: Actor, clock: FrozenClock
) -> None:
    # 21:30 UTC on 19 October is already 00:30 on the 20th in Minsk: the window is open.
    clock.set(datetime(2026, 10, 19, 21, 30, tzinfo=UTC))
    food = await category_id(client, anna, "Продукты")

    assert (await set_limit(client, ivan, food, "800")).status_code == 200


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "26-11", "november"])
async def test_months_are_written_as_yyyy_mm(client: AsyncClient, anna: Actor, month: str) -> None:
    response = await client.get(f"/budgets/{month}", headers=anna.headers)

    assert response.status_code == 422


@pytest.mark.parametrize("amount", ["0", "-1", "1.001"])
async def test_limits_must_be_positive_cents(client: AsyncClient, anna: Actor, amount: str) -> None:
    food = await category_id(client, anna, "Продукты")

    assert (await set_limit(client, anna, food, amount)).status_code == 422


async def test_budgets_of_another_household_are_invisible(client: AsyncClient, anna: Actor) -> None:
    bob = await sign_up(client, "bob@example.com")
    food = await category_id(client, anna, "Продукты")
    await set_limit(client, anna, food, "800")

    assert (await budget(client, bob))["limits"] == []
    # Anna's category does not exist for Bob.
    await assert_hidden_from(
        client, bob, "PUT", f"/budgets/{NOVEMBER}/limits/{food}", json={"amount": "1"}
    )


async def test_budgets_require_authentication(client: AsyncClient) -> None:
    assert (await client.get(f"/budgets/{NOVEMBER}")).status_code == 401


async def test_an_archived_category_takes_no_limit(client: AsyncClient, anna: Actor) -> None:
    food = await category_id(client, anna, "Продукты")
    await client.patch(f"/categories/{food}", headers=anna.headers, json={"archived": True})

    response = await set_limit(client, anna, food, "100")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "archived"


async def test_removing_a_limit_that_is_not_set_is_not_found(
    client: AsyncClient, anna: Actor
) -> None:
    food = await category_id(client, anna, "Продукты")
    taxi = await category_id(client, anna, "Транспорт")
    await set_limit(client, anna, food, "100")

    no_budget = await client.delete(f"/budgets/2027-01/limits/{food}", headers=anna.headers)
    no_limit = await client.delete(f"/budgets/{NOVEMBER}/limits/{taxi}", headers=anna.headers)

    assert no_budget.status_code == no_limit.status_code == 404


async def test_approving_twice_keeps_the_first_approval(
    client: AsyncClient, anna: Actor, clock: FrozenClock
) -> None:
    await set_limit(client, anna, await category_id(client, anna, "Продукты"), "100")
    first = (await client.post(f"/budgets/{NOVEMBER}/approve", headers=anna.headers)).json()
    clock.advance(timedelta(minutes=5))

    second = (await client.post(f"/budgets/{NOVEMBER}/approve", headers=anna.headers)).json()

    assert second["approved_at"] == first["approved_at"]
