"""Which approval reminders are due on a day, and when a budget counts as not approved."""

from datetime import date

import pytest

from family_pnl.domain.budgets import (
    DEFAULT_WINDOW,
    ApprovalReminder,
    BudgetStatus,
    approval_missed,
    due_reminders,
)
from family_pnl.domain.notifications import reminder_message

OCTOBER = date(2026, 10, 1)
NOVEMBER = date(2026, 11, 1)
NOVEMBER_CLOSES = date(2026, 10, 30)
OCTOBER_CLOSES = date(2026, 9, 30)


def due(today: date, *approved: date) -> list[ApprovalReminder]:
    return due_reminders(today=today, window=DEFAULT_WINDOW, approved=frozenset(approved))


def test_no_reminder_before_the_window_opens_when_this_month_is_approved() -> None:
    assert due(date(2026, 10, 19), OCTOBER) == []


@pytest.mark.parametrize("day", [20, 25, 30])
def test_from_day_20_the_next_month_is_reminded_while_the_window_is_open(day: int) -> None:
    assert due(date(2026, 10, day), OCTOBER) == [
        ApprovalReminder(NOVEMBER, NOVEMBER_CLOSES, missed=False)
    ]


def test_after_the_window_closes_the_reminder_says_it_was_missed() -> None:
    assert due(date(2026, 10, 31), OCTOBER) == [
        ApprovalReminder(NOVEMBER, NOVEMBER_CLOSES, missed=True)
    ]


def test_an_approved_budget_is_not_reminded() -> None:
    assert due(date(2026, 10, 25), OCTOBER, NOVEMBER) == []


def test_a_month_that_started_without_approval_keeps_being_reminded() -> None:
    assert due(date(2026, 10, 5)) == [ApprovalReminder(OCTOBER, OCTOBER_CLOSES, missed=True)]


def test_both_months_are_reminded_when_neither_is_approved() -> None:
    assert due(date(2026, 10, 22)) == [
        ApprovalReminder(OCTOBER, OCTOBER_CLOSES, missed=True),
        ApprovalReminder(NOVEMBER, NOVEMBER_CLOSES, missed=False),
    ]


def test_in_december_the_next_budget_is_januarys() -> None:
    assert due(date(2026, 12, 21), date(2026, 12, 1)) == [
        ApprovalReminder(date(2027, 1, 1), date(2026, 12, 30), missed=False)
    ]


@pytest.mark.parametrize(
    ("status", "today", "missed"),
    [
        (BudgetStatus.DRAFT, date(2026, 10, 30), False),
        (BudgetStatus.DRAFT, date(2026, 10, 31), True),
        (BudgetStatus.APPROVED, date(2026, 10, 31), False),
    ],
)
def test_a_budget_is_not_approved_once_its_window_closed_without_approval(
    status: BudgetStatus, today: date, missed: bool
) -> None:
    assert approval_missed(status=status, today=today, window_closes=NOVEMBER_CLOSES) is missed


def test_the_reminder_while_the_window_is_open() -> None:
    assert reminder_message(month="2026-11", window_closes="2026-10-30", missed=False) == (
        "Бюджет на 2026-11 ещё не утверждён. Окно утверждения открыто до 2026-10-30."
    )


def test_the_reminder_after_the_window_closed() -> None:
    assert reminder_message(month="2026-11", window_closes="2026-10-30", missed=True) == (
        "Бюджет на 2026-11 не утверждён: окно утверждения закрылось 2026-10-30."
    )
