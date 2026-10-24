from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from family_pnl.core.errors import PermissionDeniedError
from family_pnl.domain.budgets import (
    DEFAULT_WINDOW,
    THRESHOLDS,
    ApprovalWindow,
    BudgetStatus,
    first_of_month,
    local_today,
    next_month,
    previous_month,
    reached_thresholds,
    require_budget_approver,
    require_budget_editor,
)
from family_pnl.domain.identity import Role

MINSK = ZoneInfo("Europe/Minsk")


def test_the_default_window_is_from_the_20th_to_the_30th() -> None:
    assert (DEFAULT_WINDOW.start_day, DEFAULT_WINDOW.end_day) == (20, 30)


def test_budget_statuses_have_stable_values() -> None:
    assert [s.value for s in BudgetStatus] == ["draft", "approved"]


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 10, 24), date(2026, 10, 1)), (date(2026, 10, 1), date(2026, 10, 1))],
)
def test_first_of_month(day: date, expected: date) -> None:
    assert first_of_month(day) == expected


@pytest.mark.parametrize(
    ("month", "expected"),
    [(date(2026, 10, 1), date(2026, 11, 1)), (date(2026, 12, 1), date(2027, 1, 1))],
    ids=["within-year", "december"],
)
def test_next_month(month: date, expected: date) -> None:
    assert next_month(month) == expected


@pytest.mark.parametrize(
    ("budget_month", "opens", "closes"),
    [
        (date(2026, 11, 1), date(2026, 10, 20), date(2026, 10, 30)),  # 31-day October
        (date(2026, 12, 1), date(2026, 11, 20), date(2026, 11, 30)),  # 30-day November
        (date(2027, 3, 1), date(2027, 2, 20), date(2027, 2, 28)),  # 28-day February
        (date(2028, 3, 1), date(2028, 2, 20), date(2028, 2, 29)),  # leap February
        (date(2027, 1, 1), date(2026, 12, 20), date(2026, 12, 30)),  # across the year
    ],
    ids=["31-days", "30-days", "28-days", "29-days", "new-year"],
)
def test_the_window_lies_in_the_month_before_the_budget(
    budget_month: date, opens: date, closes: date
) -> None:
    assert DEFAULT_WINDOW.bounds(budget_month) == (opens, closes)


@pytest.mark.parametrize(
    ("today", "open_"),
    [
        (date(2026, 10, 19), False),
        (date(2026, 10, 20), True),
        (date(2026, 10, 30), True),
        (date(2026, 10, 31), False),
        (date(2026, 11, 5), False),
        (date(2026, 9, 25), False),  # the window for October, not November
    ],
)
def test_the_window_for_november_is_open_from_the_20th_to_the_30th_of_october(
    today: date, open_: bool
) -> None:
    assert DEFAULT_WINDOW.is_open(today, date(2026, 11, 1)) is open_


def test_february_windows_close_on_its_last_day() -> None:
    assert DEFAULT_WINDOW.is_open(date(2027, 2, 28), date(2027, 3, 1)) is True
    assert DEFAULT_WINDOW.is_open(date(2027, 3, 1), date(2027, 3, 1)) is False


def test_a_custom_window() -> None:
    window = ApprovalWindow(start_day=25, end_day=31)

    assert window.bounds(date(2026, 12, 1)) == (date(2026, 11, 25), date(2026, 11, 30))


@pytest.mark.parametrize(
    ("start", "end"),
    [(0, 30), (20, 32), (21, 20)],
    ids=["start-zero", "end-past-31", "start-after-end"],
)
def test_impossible_windows_are_rejected(start: int, end: int) -> None:
    expected = rf"^approval window must satisfy 1 <= start <= end <= 31, got {start}\.\.{end}$"
    with pytest.raises(ValueError, match=expected):
        ApprovalWindow(start_day=start, end_day=end)


def test_a_single_day_window_is_allowed() -> None:
    assert ApprovalWindow(start_day=1, end_day=1).bounds(date(2026, 11, 1)) == (
        date(2026, 10, 1),
        date(2026, 10, 1),
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 19, 20, 59, tzinfo=UTC), date(2026, 10, 19)),  # 23:59 in Minsk
        (datetime(2026, 10, 19, 21, 0, tzinfo=UTC), date(2026, 10, 20)),  # midnight in Minsk
    ],
)
def test_today_is_the_household_date(now: datetime, expected: date) -> None:
    assert local_today(now, MINSK) == expected


NOVEMBER = date(2026, 11, 1)
INSIDE = date(2026, 10, 25)
OUTSIDE = date(2026, 10, 10)


@pytest.mark.parametrize(
    ("role", "status", "today", "allowed"),
    [
        (Role.MEMBER, BudgetStatus.DRAFT, INSIDE, True),
        (Role.MEMBER, BudgetStatus.DRAFT, OUTSIDE, False),
        (Role.MEMBER, BudgetStatus.APPROVED, INSIDE, False),
        (Role.MEMBER, BudgetStatus.APPROVED, OUTSIDE, False),
        (Role.OWNER, BudgetStatus.DRAFT, INSIDE, True),
        (Role.OWNER, BudgetStatus.DRAFT, OUTSIDE, True),
        (Role.OWNER, BudgetStatus.APPROVED, INSIDE, True),
        (Role.OWNER, BudgetStatus.APPROVED, OUTSIDE, True),
    ],
)
def test_who_may_change_a_budget(
    role: Role, status: BudgetStatus, today: date, allowed: bool
) -> None:
    def change() -> None:
        require_budget_editor(
            role=role, status=status, today=today, budget_month=NOVEMBER, window=DEFAULT_WINDOW
        )

    if allowed:
        change()
    else:
        with pytest.raises(PermissionDeniedError) as info:
            change()
        assert info.value.message == (
            "Outside the approval window or after approval only the owner can change the budget"
        )


def test_only_the_owner_approves() -> None:
    require_budget_approver(Role.OWNER)

    with pytest.raises(PermissionDeniedError) as info:
        require_budget_approver(Role.MEMBER)

    assert info.value.message == "Only the household owner can approve the budget"


@pytest.mark.parametrize(
    ("month", "expected"),
    [(date(2026, 11, 1), date(2026, 10, 1)), (date(2027, 1, 1), date(2026, 12, 1))],
    ids=["within-year", "january"],
)
def test_previous_month(month: date, expected: date) -> None:
    assert previous_month(month) == expected


@pytest.mark.parametrize("month", range(1, 13))
def test_next_and_previous_month_are_inverse_for_every_month(month: int) -> None:
    first = date(2026, month, 1)

    assert previous_month(next_month(first)) == first
    assert next_month(previous_month(first)) == first


def test_thresholds_are_80_and_100_percent() -> None:
    assert THRESHOLDS == (80, 100)


@pytest.mark.parametrize(
    ("spent", "limit", "reached"),
    [
        ("0", "100", ()),
        ("79.99", "100", ()),
        ("80", "100", (80,)),
        ("99.99", "100", (80,)),
        ("100", "100", (80, 100)),
        ("250", "100", (80, 100)),
        ("0.08", "0.10", (80,)),
    ],
)
def test_reached_thresholds(spent: str, limit: str, reached: tuple[int, ...]) -> None:
    assert reached_thresholds(Decimal(spent), Decimal(limit)) == reached


def test_a_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^limit must be positive, got 0$"):
        reached_thresholds(Decimal("5"), Decimal("0"))
