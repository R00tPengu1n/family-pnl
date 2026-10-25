"""/budget, /limit and approval in the bot against the real API."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from family_pnl.core.clock import FrozenClock
from family_pnl_bot import messages
from family_pnl_bot.api_client import ApiClient, ApiError, Me
from family_pnl_bot.budget import BudgetBot
from family_pnl_bot.replies import start_reply

ANNA, IVAN = 5000000001, 5000000002
INSIDE = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)  # the November window: 20-30 October
OUTSIDE = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(INSIDE)


@pytest.fixture
async def family(api: ApiClient) -> None:
    """Anna owns the household, Ivan is a member; both registered through the bot."""
    await start_reply(api, ANNA, "Анна", None)
    code = (await api.request(ANNA, "POST", "/household/invites"))["code"]
    await start_reply(api, IVAN, "Иван", code)


def bot(api: ApiClient, now: datetime = INSIDE) -> BudgetBot:
    return BudgetBot(api, now=lambda: now)


@pytest.mark.usefixtures("family")
async def test_a_member_sets_a_limit_inside_the_window(api: ApiClient) -> None:
    reply = await bot(api).set_limit(IVAN, "прод 800,5")

    assert reply.text == "Лимит «Продукты» на ноябрь 2026: 800.50 RUB."
    limits = (await api.request(ANNA, "GET", "/budgets/2026-11"))["limits"]
    assert [(item["category"], item["amount"]) for item in limits] == [("Продукты", "800.50")]


@pytest.mark.usefixtures("family")
async def test_outside_the_window_a_member_gets_a_clear_message(
    api: ApiClient, clock: FrozenClock
) -> None:
    clock.set(OUTSIDE)

    reply = await bot(api, OUTSIDE).set_limit(IVAN, "продукты 800")

    assert reply.text == (
        "Сейчас менять бюджет может только владелец: окно утверждения закрыто "
        "или бюджет уже утверждён."
    )


@pytest.mark.usefixtures("family")
async def test_only_the_owner_sees_the_approve_button(api: ApiClient) -> None:
    await bot(api).set_limit(ANNA, "продукты 800")

    owner = await bot(api).view(ANNA)
    member = await bot(api).view(IVAN)

    assert [[b.text for b in row] for row in owner.buttons] == [["Утвердить"]]
    assert owner.buttons[0][0].data == "bud:approve:2026-11"
    assert member.buttons == ()
    assert owner.text == member.text
    assert owner.text.splitlines() == [
        "Бюджет на ноябрь 2026, RUB: черновик",
        "Окно утверждения: 20.10–30.10 (открыто)",
        "• Продукты — 800.00",
        "",
        "Октябрь 2026, RUB: потрачено из лимита",
        "Бюджета на этот месяц нет.",
    ]


@pytest.mark.usefixtures("family")
async def test_the_owner_approves_and_the_button_goes(api: ApiClient) -> None:
    await bot(api).set_limit(ANNA, "продукты 800")

    reply = await bot(api).approve(ANNA, "bud:approve:2026-11")

    assert reply.text == "Бюджет на ноябрь 2026 утверждён."
    after = await bot(api).view(ANNA)
    assert after.buttons == ()
    assert after.text.splitlines()[0] == "Бюджет на ноябрь 2026, RUB: утверждён"


@pytest.mark.usefixtures("family")
async def test_a_member_pressing_approve_is_refused(api: ApiClient) -> None:
    await bot(api).set_limit(ANNA, "продукты 800")

    reply = await bot(api).approve(IVAN, "bud:approve:2026-11")

    assert reply.text == "Утвердить бюджет может только владелец семьи."
    assert (await api.request(ANNA, "GET", "/budgets/2026-11"))["status"] == "draft"


@pytest.mark.usefixtures("family")
async def test_approving_a_month_without_limits_says_what_to_do(api: ApiClient) -> None:
    reply = await bot(api).approve(ANNA, "bud:approve:2026-11")

    assert reply.text == "Бюджета на этот месяц ещё нет: сначала задайте лимиты через /limit."


@pytest.mark.usefixtures("family")
async def test_the_current_month_shows_spending_against_limits(
    api: ApiClient, clock: FrozenClock
) -> None:
    await bot(api).set_limit(ANNA, "продукты 400")  # the owner plans October too
    await api.request(
        ANNA, "PUT", "/budgets/2026-10/limits/" + await _food(api), json={"amount": "400"}
    )
    card = await api.request(
        ANNA, "POST", "/accounts", json={"name": "Card", "type": "card", "currency": "RUB"}
    )
    await api.request(
        ANNA,
        "POST",
        "/operations",
        json={
            "type": "expense",
            "amount": "100",
            "currency": "RUB",
            "account_id": card["id"],
            "category_id": await _food(api),
            "operation_date": "2026-10-20",
        },
    )

    lines = (await bot(api).view(ANNA)).text.splitlines()

    assert lines[-2:] == [
        "Октябрь 2026, RUB: потрачено из лимита",
        "• Продукты: 100.00 из 400.00 (25.0%)",
    ]


async def _food(api: ApiClient) -> str:
    categories = await api.request(ANNA, "GET", "/categories", params={"kind": "expense"})
    food: str = next(c["id"] for c in categories if c["name"] == "Продукты")
    return food


@pytest.mark.usefixtures("family")
async def test_a_missed_window_is_shown(api: ApiClient, clock: FrozenClock) -> None:
    late = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
    clock.set(late)

    first = (await bot(api, late).view(ANNA)).text.splitlines()[:2]

    assert first == [
        "Бюджет на ноябрь 2026, RUB: не утверждён: окно закрылось",
        "Окно утверждения: 20.10–30.10",
    ]


@pytest.mark.parametrize(
    "args", [None, "продукты", "продукты много", "продукты 0", "продукты 1.005", "продукты NaN"]
)
async def test_a_limit_command_without_a_valid_amount_shows_how(args: str | None) -> None:
    # Refused before any API call, so the API is not needed.
    reply = await BudgetBot(cast(ApiClient, DownApi()), now=lambda: INSIDE).set_limit(ANNA, args)

    assert reply.text == "Напишите категорию и сумму: /limit продукты 800"


@pytest.mark.usefixtures("family")
async def test_a_limit_for_a_category_that_is_not_an_expense_is_explained(
    api: ApiClient,
) -> None:
    assert (await bot(api).set_limit(ANNA, "зарплата 800")).text == (
        "Не нашёл категорию расходов «зарплата»."
    )


class DownApi:
    async def me(self, telegram_id: int) -> Me:
        raise ApiError(0, "api_unavailable", "")

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        raise ApiError(0, "api_unavailable", "")


@pytest.mark.parametrize("action", ["view", "set_limit", "approve"])
async def test_api_errors_are_explained(action: str) -> None:
    budget = BudgetBot(cast(ApiClient, DownApi()), now=lambda: INSIDE)
    calls = {
        "view": lambda: budget.view(ANNA),
        "set_limit": lambda: budget.set_limit(ANNA, "продукты 800"),
        "approve": lambda: budget.approve(ANNA, "bud:approve:2026-11"),
    }

    assert (await calls[action]()).text == messages.ERRORS["api_unavailable"]
