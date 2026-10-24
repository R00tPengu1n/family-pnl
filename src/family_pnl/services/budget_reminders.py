"""Daily reminders to the owner while a budget is not approved (SPEC: budgets).

From the day the approval window of next month's budget opens, the owner is reminded
once a day until it is approved. A window that closes without approval leaves the budget
not approved, and the reminders continue. Reminders are written to the outbox (ADR-0009)
at or after 09:00 household time; the dedupe key holds the date, so one per day.
"""

import uuid
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.config import Settings
from family_pnl.domain.budgets import ApprovalWindow, due_reminders, first_of_month, next_month
from family_pnl.repositories.budgets import BudgetRepository
from family_pnl.repositories.identity import HouseholdRepository
from family_pnl.repositories.notifications import NotificationRepository

REMINDER_KIND = "budget_reminder"
REMINDER_HOUR = 9


class BudgetReminderService:
    def __init__(self, session: AsyncSession, clock: Clock, settings: Settings) -> None:
        self._session = session
        self._clock = clock
        self._window = ApprovalWindow(
            start_day=settings.budget_window_start_day, end_day=settings.budget_window_end_day
        )
        self._households = HouseholdRepository(session)
        self._budgets = BudgetRepository(session)
        self._notifications = NotificationRepository(session)

    async def remind(self) -> int:
        """Record today's reminders of every household; returns how many are due."""
        now = self._clock.now()
        due = 0
        for household in await self._households.all():
            local = now.astimezone(ZoneInfo(household.timezone))
            if local.hour < REMINDER_HOUR:
                continue
            today = local.date()
            current = first_of_month(today)
            approved = await self._budgets.approved_months(
                household.id, [current, next_month(current)]
            )
            for reminder in due_reminders(today=today, window=self._window, approved=approved):
                month = reminder.month.strftime("%Y-%m")
                await self._notifications.add_once(
                    notification_id=uuid.uuid4(),
                    household_id=household.id,
                    kind=REMINDER_KIND,
                    dedupe_key=f"{REMINDER_KIND}:{household.id}:{month}:{today.isoformat()}",
                    payload={
                        "month": month,
                        "window_closes": reminder.window_closes.isoformat(),
                        "missed": reminder.missed,
                    },
                    created_at=now,
                )
                due += 1
        await self._session.commit()
        return due
