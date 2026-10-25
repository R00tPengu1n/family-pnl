"""Sends due outbox notifications to Telegram every minute (ADR-0009)."""

from typing import Any

import structlog

from family_pnl.integrations.telegram import (
    BotApiSender,
    TelegramSender,
    TelegramTokenRejectedError,
)
from family_pnl.services.notifications import NotificationDelivery
from family_pnl.worker.context import WorkerContext, context_of

# At most this many per run; the rest wait for the next minute.
BATCH = 100

logger = structlog.get_logger(__name__)


async def deliver_notifications(ctx: dict[str, Any]) -> None:
    context = context_of(ctx)
    token = context.settings.telegram_bot_token
    if token is None:
        logger.warning("telegram_not_configured")
        return
    await deliver_with(context, BotApiSender(context.telegram_http, token))


async def deliver_with(context: WorkerContext, sender: TelegramSender) -> int:
    """Deliver due notifications one transaction each; returns how many were handled."""
    handled = 0
    while handled < BATCH:
        async with context.session_factory() as session:
            delivery = NotificationDelivery(session, sender, context.clock)
            try:
                if not await delivery.deliver_next():
                    break
            except TelegramTokenRejectedError as exc:
                logger.error("telegram_token_rejected", error=str(exc))
                break
        handled += 1
    return handled
