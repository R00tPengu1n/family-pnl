"""Daily approval reminders to the owner, with a fake clock and a fake sender."""

from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.models import Notification, User
from family_pnl.worker import context as worker_context
from family_pnl.worker.context import WorkerContext
from family_pnl.worker.jobs.budgets import remind_with, send_budget_reminders
from family_pnl.worker.jobs.notifications import deliver_with
from tests.integration.helpers import Actor, join_household, sign_up
from tests.integration.ledger_helpers import category_id
from tests.integration.worker.test_notification_delivery import FakeSender

ANNA_CHAT, IVAN_CHAT = 1001, 2002


def minsk(day: int, hour: int, month: int = 10) -> datetime:
    """`hour` o'clock in Minsk (UTC+3)."""
    return datetime(2026, month, day, hour - 3, 0, tzinfo=UTC)


@pytest.fixture
async def anna(client: AsyncClient, db_session: AsyncSession) -> Actor:
    """The owner, with October approved; Ivan is a member. Both linked to Telegram."""
    anna = await sign_up(client, "anna@example.com")
    ivan = await join_household(client, anna, "ivan@example.com")
    for user, chat in ((anna, ANNA_CHAT), (ivan, IVAN_CHAT)):
        await db_session.execute(
            update(User).where(User.id == user.user_id).values(telegram_id=chat)
        )
    food = await category_id(client, anna, "Продукты")
    await client.put(f"/budgets/2026-10/limits/{food}", headers=anna.headers, json={"amount": "1"})
    response = await client.post("/budgets/2026-10/approve", headers=anna.headers)
    assert response.status_code == 200, response.text
    return anna


async def reminders(db_session: AsyncSession) -> list[dict[str, Any]]:
    rows = await db_session.scalars(
        select(Notification)
        .where(Notification.kind == "budget_reminder")
        .order_by(Notification.created_at, Notification.dedupe_key)
    )
    return [row.payload for row in rows]


async def remind_at(context: WorkerContext, clock: FrozenClock, moment: datetime) -> int:
    clock.set(moment)
    return await remind_with(context)


NOVEMBER_OPEN = {"month": "2026-11", "window_closes": "2026-10-30", "missed": False}


async def test_no_reminder_before_day_20(
    context: WorkerContext, worker_clock: FrozenClock, anna: Actor, db_session: AsyncSession
) -> None:
    assert await remind_at(context, worker_clock, minsk(19, 12)) == 0
    assert await reminders(db_session) == []


async def test_from_day_20_one_reminder_a_day_from_nine_oclock(
    context: WorkerContext, worker_clock: FrozenClock, anna: Actor, db_session: AsyncSession
) -> None:
    assert await remind_at(context, worker_clock, minsk(20, 8)) == 0
    await remind_at(context, worker_clock, minsk(20, 9))
    await remind_at(context, worker_clock, minsk(20, 15))  # the same day: nothing new
    assert await reminders(db_session) == [NOVEMBER_OPEN]

    await remind_at(context, worker_clock, minsk(21, 9))

    assert await reminders(db_session) == [NOVEMBER_OPEN, NOVEMBER_OPEN]


async def test_no_reminder_after_approval(
    client: AsyncClient,
    context: WorkerContext,
    worker_clock: FrozenClock,
    anna: Actor,
    db_session: AsyncSession,
) -> None:
    await remind_at(context, worker_clock, minsk(20, 9))
    food = await category_id(client, anna, "Продукты")
    await client.put(f"/budgets/2026-11/limits/{food}", headers=anna.headers, json={"amount": "1"})
    await client.post("/budgets/2026-11/approve", headers=anna.headers)

    assert await remind_at(context, worker_clock, minsk(21, 9)) == 0
    assert len(await reminders(db_session)) == 1


async def test_after_the_window_the_budget_is_not_approved_and_reminders_continue(
    context: WorkerContext, worker_clock: FrozenClock, anna: Actor, db_session: AsyncSession
) -> None:
    await remind_at(context, worker_clock, minsk(31, 9))
    await remind_at(context, worker_clock, minsk(1, 9, month=11))

    missed = {"month": "2026-11", "window_closes": "2026-10-30", "missed": True}
    assert await reminders(db_session) == [missed, missed]


async def test_only_the_owner_gets_the_reminder(
    context: WorkerContext, worker_clock: FrozenClock, anna: Actor
) -> None:
    await remind_at(context, worker_clock, minsk(20, 9))
    sender = FakeSender()

    await deliver_with(context, sender)

    assert sender.sent == [
        (ANNA_CHAT, "Бюджет на 2026-11 ещё не утверждён. Окно утверждения открыто до 2026-10-30.")
    ]


async def test_nine_oclock_is_in_the_household_time_zone(
    client: AsyncClient,
    context: WorkerContext,
    worker_clock: FrozenClock,
    anna: Actor,
    db_session: AsyncSession,
) -> None:
    await client.patch("/household/settings", headers=anna.headers, json={"timezone": "Asia/Tokyo"})

    # 01:00 UTC on 20 October: 04:00 in Minsk, already 10:00 in Tokyo.
    assert await remind_at(context, worker_clock, datetime(2026, 10, 20, 1, 0, tzinfo=UTC)) == 1


async def test_the_cron_job_logs_how_many_reminders_were_due(
    context: WorkerContext, worker_clock: FrozenClock, anna: Actor
) -> None:
    worker_clock.set(minsk(20, 9))

    with structlog.testing.capture_logs() as logs:
        await send_budget_reminders({worker_context.CONTEXT_KEY: context})

    assert {"event": "budget_reminders_checked", "due": 1, "log_level": "info"} in logs
