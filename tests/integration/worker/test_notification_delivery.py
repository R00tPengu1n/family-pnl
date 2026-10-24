"""Delivery of outbox notifications to Telegram, with a fake sender."""

import dataclasses
import json
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
import structlog
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.integrations.telegram import TelegramChatUnavailableError, TelegramSendError
from family_pnl.models import Notification, User
from family_pnl.repositories.notifications import NotificationRepository
from family_pnl.worker import context as worker_context
from family_pnl.worker.context import WorkerContext
from family_pnl.worker.jobs import notifications as job
from family_pnl.worker.jobs.notifications import deliver_notifications, deliver_with
from tests.integration.helpers import Actor, join_household, sign_up
from tests.integration.ledger_helpers import category_id
from tests.integration.worker.conftest import WORKER_NOW

ANNA_CHAT = 1001
TEXT_80 = "Бюджет 2026-10, «Продукты»: потрачено 80.00 из 100.00 BYN — 80% лимита."


class FakeSender:
    """Records messages; `failures` decides what each chat gets instead of delivery."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.failures: dict[int, Exception] = {}

    async def send(self, chat_id: int, text: str) -> None:
        if chat_id in self.failures:
            raise self.failures[chat_id]
        self.sent.append((chat_id, text))


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
async def family(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Anna (owner, Telegram linked) and Ivan (member, not linked)."""
    anna = await sign_up(client, "anna@example.com")
    ivan = await join_household(client, anna, "ivan@example.com")
    await db_session.execute(
        update(User).where(User.id == anna.user_id).values(telegram_id=ANNA_CHAT)
    )
    food = await category_id(client, anna, "Продукты")
    return {"anna": anna, "ivan": ivan, "food": food}


async def notify(
    db_session: AsyncSession,
    owner: Actor,
    category: str,
    *,
    kind: str = "budget_threshold",
    key: str = "k80",
    threshold: int = 80,
    age: timedelta = timedelta(minutes=1),
) -> uuid.UUID:
    notification_id = uuid.uuid4()
    await NotificationRepository(db_session).add_once(
        notification_id=notification_id,
        household_id=owner.household_id,
        kind=kind,
        dedupe_key=key,
        payload={
            "month": "2026-10",
            "category_id": category,
            "threshold": threshold,
            "spent": "80.00",
            "limit": "100.00",
            "currency": "BYN",
        },
        created_at=WORKER_NOW - age,
    )
    return notification_id


async def row(db_session: AsyncSession, notification_id: uuid.UUID) -> Notification:
    found = await db_session.scalar(
        select(Notification)
        .where(Notification.id == notification_id)
        .execution_options(populate_existing=True)
    )
    assert found is not None
    return found


async def test_a_notification_reaches_linked_members_and_is_marked_sent(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    notification_id = await notify(db_session, family["anna"], family["food"])

    with structlog.testing.capture_logs() as logs:
        handled = await deliver_with(context, sender)

    assert handled == 1
    assert sender.sent == [(ANNA_CHAT, TEXT_80)]
    sent = await row(db_session, notification_id)
    assert (sent.sent_at, sent.attempts, sent.gave_up_at) == (WORKER_NOW, 1, None)
    skipped = [log for log in logs if log["event"] == "notification_recipient_not_linked"]
    assert [log["user_id"] for log in skipped] == [str(family["ivan"].user_id)]


async def test_a_sent_notification_is_not_sent_again_after_a_restart(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
    worker_clock: FrozenClock,
) -> None:
    await notify(db_session, family["anna"], family["food"])
    await deliver_with(context, sender)

    worker_clock.advance(timedelta(hours=1))
    restarted = dataclasses.replace(context)
    handled = await deliver_with(restarted, sender)

    assert handled == 0
    assert len(sender.sent) == 1


async def test_a_failure_that_may_pass_postpones_with_a_growing_delay(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
    worker_clock: FrozenClock,
) -> None:
    notification_id = await notify(db_session, family["anna"], family["food"])
    sender.failures[ANNA_CHAT] = TelegramSendError("Telegram answered HTTP 502")

    await deliver_with(context, sender)
    first = await row(db_session, notification_id)
    assert (first.attempts, first.next_attempt_at, first.sent_at) == (
        1,
        WORKER_NOW + timedelta(minutes=1),
        None,
    )

    worker_clock.advance(timedelta(seconds=59))
    assert await deliver_with(context, sender) == 0  # not due yet

    worker_clock.advance(timedelta(seconds=1))
    await deliver_with(context, sender)
    second = await row(db_session, notification_id)
    assert (second.attempts, second.next_attempt_at) == (
        2,
        WORKER_NOW + timedelta(minutes=1) + timedelta(minutes=2),
    )

    del sender.failures[ANNA_CHAT]
    worker_clock.advance(timedelta(minutes=2))
    await deliver_with(context, sender)
    assert (await row(db_session, notification_id)).sent_at == worker_clock.now()
    assert sender.sent == [(ANNA_CHAT, TEXT_80)]


async def test_delivery_is_given_up_after_ten_failures(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
    worker_clock: FrozenClock,
) -> None:
    notification_id = await notify(db_session, family["anna"], family["food"])
    sender.failures[ANNA_CHAT] = TelegramSendError("Telegram request failed: ConnectError")

    with structlog.testing.capture_logs() as logs:
        for _ in range(10):
            await deliver_with(context, sender)
            worker_clock.advance(timedelta(hours=6))

    given_up = await row(db_session, notification_id)
    assert (given_up.attempts, given_up.sent_at) == (10, None)
    assert given_up.gave_up_at == WORKER_NOW + timedelta(hours=6 * 9)
    assert [log["event"] for log in logs if log["log_level"] == "error"] == [
        "notification_given_up"
    ]
    assert await deliver_with(context, sender) == 0


async def test_a_chat_that_refuses_the_bot_is_skipped_and_the_rest_delivered(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    notification_id = await notify(db_session, family["anna"], family["food"])
    await db_session.execute(
        update(User).where(User.id == family["ivan"].user_id).values(telegram_id=2002)
    )
    sender.failures[ANNA_CHAT] = TelegramChatUnavailableError("Telegram answered HTTP 403")

    with structlog.testing.capture_logs() as logs:
        await deliver_with(context, sender)

    assert sender.sent == [(2002, TEXT_80)]
    assert (await row(db_session, notification_id)).sent_at == WORKER_NOW
    assert [log["user_id"] for log in logs if log["event"] == "notification_chat_unavailable"] == [
        str(family["anna"].user_id)
    ]


async def test_notifications_go_oldest_first_and_one_run_handles_a_batch(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await notify(db_session, family["anna"], family["food"], key="a", age=timedelta(minutes=2))
    await notify(db_session, family["anna"], family["food"], key="b", threshold=100)
    monkeypatch.setattr(job, "BATCH", 1)

    assert await deliver_with(context, sender) == 1
    assert await deliver_with(context, sender) == 1
    assert await deliver_with(context, sender) == 0

    assert [text for _, text in sender.sent] == [
        TEXT_80,
        "Бюджет 2026-10, «Продукты»: лимит исчерпан — потрачено 80.00 из 100.00 BYN.",
    ]


async def test_an_unknown_kind_is_given_up(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    notification_id = await notify(db_session, family["anna"], family["food"], kind="mystery")

    with structlog.testing.capture_logs() as logs:
        await deliver_with(context, sender)

    assert sender.sent == []
    assert (await row(db_session, notification_id)).gave_up_at == WORKER_NOW
    assert "notification_kind_unknown" in [log["event"] for log in logs]


async def test_a_missing_category_still_sends_the_message(
    context: WorkerContext,
    sender: FakeSender,
    family: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    await notify(db_session, family["anna"], str(uuid.uuid4()))

    await deliver_with(context, sender)

    assert sender.sent == [(ANNA_CHAT, TEXT_80.replace("Продукты", "?"))]


async def test_without_a_token_notifications_wait(
    context: WorkerContext, family: dict[str, Any], db_session: AsyncSession
) -> None:
    notification_id = await notify(db_session, family["anna"], family["food"])

    with structlog.testing.capture_logs() as logs:
        await deliver_notifications({worker_context.CONTEXT_KEY: context})

    assert [log["event"] for log in logs] == ["telegram_not_configured"]
    assert (await row(db_session, notification_id)).sent_at is None


async def test_with_a_token_the_cron_job_sends_through_the_bot_api(
    context: WorkerContext, family: dict[str, Any], db_session: AsyncSession
) -> None:
    await notify(db_session, family["anna"], family["food"])
    posted: list[tuple[str, dict[str, Any]]] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    http = httpx.AsyncClient(
        base_url="https://telegram.test", transport=httpx.MockTransport(telegram)
    )
    settings = context.settings.model_copy(update={"telegram_bot_token": SecretStr("1:t")})
    configured = dataclasses.replace(context, settings=settings, telegram_http=http)

    await deliver_notifications({worker_context.CONTEXT_KEY: configured})
    await http.aclose()

    assert posted == [("/bot1:t/sendMessage", {"chat_id": ANNA_CHAT, "text": TEXT_80})]
