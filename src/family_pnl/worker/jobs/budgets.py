"""Hourly check for budget approval reminders; each household gets one a day."""

from typing import Any

import structlog

from family_pnl.services.budget_reminders import BudgetReminderService
from family_pnl.worker.context import WorkerContext, context_of

logger = structlog.get_logger(__name__)


async def send_budget_reminders(ctx: dict[str, Any]) -> None:
    await remind_with(context_of(ctx))


async def remind_with(context: WorkerContext) -> int:
    async with context.session_factory() as session:
        due = await BudgetReminderService(session, context.clock, context.settings).remind()
    logger.info("budget_reminders_checked", due=due)
    return due
