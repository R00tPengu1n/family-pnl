"""Budget rules: the approval window and who may change or approve a budget.

The budget of a month is prepared in the month before it: from `start_day` to `end_day`
(default the 20th to the 30th; in shorter months up to their last day). Inside the window
any member edits a draft and only the owner approves; outside it, and once approved, only
the owner changes the budget. All dates are household dates (`local_today`).
"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime
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
