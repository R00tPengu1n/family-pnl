"""Budget rules: the approval window and who may change or approve a budget.

The budget of a month is prepared in the month before it: from `start_day` to `end_day`
(default the 20th to the 30th; in shorter months up to their last day). Inside the window
any member edits a draft and only the owner approves; outside it, and once approved, only
the owner changes the budget. All dates are household dates (`local_today`).
"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from family_pnl.core.errors import PermissionDeniedError
from family_pnl.domain.identity import Role


class BudgetStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def next_month(month: date) -> date:
    """The first day of the month after `month`."""
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def previous_month(month: date) -> date:
    """The first day of the month before `month`."""
    return date(month.year - (month.month == 1), (month.month - 2) % 12 + 1, 1)


def local_today(now: datetime, timezone: ZoneInfo) -> date:
    return now.astimezone(timezone).date()


@dataclass(frozen=True, slots=True)
class ApprovalWindow:
    start_day: int
    end_day: int

    def __post_init__(self) -> None:
        if not 1 <= self.start_day <= self.end_day <= 31:
            raise ValueError(
                "approval window must satisfy 1 <= start <= end <= 31, "
                f"got {self.start_day}..{self.end_day}"
            )

    def bounds(self, budget_month: date) -> tuple[date, date]:
        """First and last day (inclusive) of the window for the budget of `budget_month`."""
        previous = previous_month(budget_month)
        last_day = calendar.monthrange(previous.year, previous.month)[1]
        return (
            previous.replace(day=min(self.start_day, last_day)),
            previous.replace(day=min(self.end_day, last_day)),
        )

    def is_open(self, today: date, budget_month: date) -> bool:
        opens, closes = self.bounds(budget_month)
        return opens <= today <= closes


DEFAULT_WINDOW = ApprovalWindow(start_day=20, end_day=30)


def require_budget_editor(
    *,
    role: Role,
    status: BudgetStatus,
    today: date,
    budget_month: date,
    window: ApprovalWindow,
) -> None:
    if role is Role.OWNER:
        return
    if status is BudgetStatus.DRAFT and window.is_open(today, budget_month):
        return
    raise PermissionDeniedError(
        "Outside the approval window or after approval only the owner can change the budget"
    )


def require_budget_approver(role: Role) -> None:
    if role is not Role.OWNER:
        raise PermissionDeniedError("Only the household owner can approve the budget")


# Members are notified once per threshold, category and month.
THRESHOLDS = (80, 100)


def reached_thresholds(spent: Decimal, limit: Decimal) -> tuple[int, ...]:
    """The thresholds (percent of the limit) that `spent` has reached."""
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    return tuple(t for t in THRESHOLDS if spent * 100 >= limit * t)


def approval_missed(*, status: BudgetStatus, today: date, window_closes: date) -> bool:
    """A budget the window closed on without approval is marked not approved."""
    return status is not BudgetStatus.APPROVED and today > window_closes


@dataclass(frozen=True, slots=True)
class ApprovalReminder:
    month: date
    window_closes: date
    missed: bool  # the window has closed; the budget stays not approved until approved


def due_reminders(
    *, today: date, window: ApprovalWindow, approved: frozenset[date]
) -> list[ApprovalReminder]:
    """What the owner is reminded of today: budgets whose window has opened, not approved.

    That is the next month's budget from the day its window opens, and the current month's
    budget if its window (last month) closed without approval.
    """
    current = first_of_month(today)
    reminders = []
    for month in (current, next_month(current)):
        opens, closes = window.bounds(month)
        if today >= opens and month not in approved:
            reminders.append(ApprovalReminder(month, closes, missed=today > closes))
    return reminders
