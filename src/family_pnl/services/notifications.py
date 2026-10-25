"""Delivery of outbox notifications to Telegram (ADR-0009).

One notification at a time, each in its own transaction: the row is locked, sent to every
recipient, marked sent and committed, so a restart never sends a delivered row again.
Members without a linked Telegram, and chats that refuse the bot, are skipped with a log
entry: retrying would not reach them and would repeat the message for everyone else. A
failure that may pass (network, rate limit, Telegram down) postpones the notification
with a growing delay, until it is given up; the members it already reached are
remembered and not sent it again. Any other error postpones it the same way, so one
broken row never blocks the rows behind it.
"""

import uuid
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.domain.identity import Role
from family_pnl.domain.notifications import (
    gives_up,
    reminder_message,
    retry_delay,
    threshold_message,
)
from family_pnl.integrations.telegram import (
    TelegramChatUnavailableError,
    TelegramSender,
    TelegramSendError,
)
from family_pnl.models import Notification, User
from family_pnl.repositories.identity import HouseholdRepository
from family_pnl.repositories.ledger import CategoryRepository
from family_pnl.repositories.notifications import NotificationRepository
from family_pnl.services.budget_execution import THRESHOLD_KIND
from family_pnl.services.budget_reminders import REMINDER_KIND

logger = structlog.get_logger(__name__)


class NotificationDelivery:
    def __init__(self, session: AsyncSession, sender: TelegramSender, clock: Clock) -> None:
        self._session = session
        self._sender = sender
        self._clock = clock
        self._notifications = NotificationRepository(session)
        self._households = HouseholdRepository(session)
        self._categories = CategoryRepository(session)

    async def deliver_next(self) -> bool:
        """Deliver the oldest due notification; False when none is due."""
        now = self._clock.now()
        notification = await self._notifications.lock_next_due(now)
        if notification is None:
            return False
        notification_id = notification.id
        log = logger.bind(notification_id=str(notification_id), kind=notification.kind)
        try:
            await self._deliver(notification, now, log)
        except Exception as exc:
            # A row that cannot be handled (a broken payload, say) must not stay first in
            # the queue forever: it is retried later like a failed send, then given up.
            log.exception("notification_failed")
            await self._session.rollback()
            self._postpone(
                await self._notifications.lock(notification_id), now, type(exc).__name__, log
            )
        await self._session.commit()
        return True

    async def _deliver(
        self, notification: Notification, now: datetime, log: structlog.BoundLogger
    ) -> None:
        text = await self._text(notification)
        if text is None:
            log.error("notification_kind_unknown")
            notification.gave_up_at = now
            return
        try:
            for user in await self._recipients(notification):
                if str(user.id) not in notification.delivered_to:
                    await self._send(user, text, log)
                    notification.delivered_to = [*notification.delivered_to, str(user.id)]
        except TelegramSendError as exc:
            self._postpone(notification, now, str(exc), log)
            return
        notification.attempts += 1
        notification.sent_at = now
        log.info("notification_sent")

    async def _send(self, user: User, text: str, log: structlog.BoundLogger) -> None:
        """Send to one member; one who cannot be reached counts as handled."""
        if user.telegram_id is None:
            log.info("notification_recipient_not_linked", user_id=str(user.id))
            return
        try:
            await self._sender.send(user.telegram_id, text)
        except TelegramChatUnavailableError as exc:
            log.warning("notification_chat_unavailable", user_id=str(user.id), error=str(exc))

    def _postpone(
        self, notification: Notification, now: datetime, error: str, log: structlog.BoundLogger
    ) -> None:
        notification.attempts += 1
        if gives_up(notification.attempts):
            notification.gave_up_at = now
            log.error("notification_given_up", attempts=notification.attempts, error=error)
            return
        notification.next_attempt_at = now + retry_delay(notification.attempts)
        log.warning("notification_postponed", attempts=notification.attempts, error=error)

    async def _recipients(self, notification: Notification) -> list[User]:
        # Thresholds concern everyone who spends from the budget; approval, the owner.
        members = await self._households.list_members(notification.household_id)
        if notification.kind == REMINDER_KIND:
            return [user for membership, user in members if membership.role is Role.OWNER]
        return [user for _, user in members]

    async def _text(self, notification: Notification) -> str | None:
        payload = notification.payload
        if notification.kind == REMINDER_KIND:
            return reminder_message(
                month=payload["month"],
                window_closes=payload["window_closes"],
                missed=payload["missed"],
            )
        if notification.kind != THRESHOLD_KIND:
            return None
        category = await self._categories.get(
            notification.household_id, uuid.UUID(payload["category_id"])
        )
        return threshold_message(
            month=payload["month"],
            category=category.name if category else "?",
            threshold=payload["threshold"],
            spent=payload["spent"],
            limit=payload["limit"],
            currency=payload["currency"],
        )
