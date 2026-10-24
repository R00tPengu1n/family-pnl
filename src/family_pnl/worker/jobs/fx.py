"""Daily refresh of the official NBRB rates (ADR-0008).

Stores the rates set for today in Minsk, where NBRB sets them. Requests that need a rate
fetch it themselves, so this job only keeps the common case fast; a failed run loses
nothing. Storing is idempotent: a rate already stored for the date is kept.
"""

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from family_pnl.domain.budgets import local_today
from family_pnl.integrations.nbrb import NbrbClient, RateSourceUnavailableError
from family_pnl.services.fx import RateService, RateSource
from family_pnl.worker.context import WorkerContext, context_of

NBRB_TIMEZONE = ZoneInfo("Europe/Minsk")

logger = structlog.get_logger(__name__)


async def refresh_rates(ctx: dict[str, Any]) -> None:
    context = context_of(ctx)
    await refresh_rates_with(context, NbrbClient(context.nbrb_http))


async def refresh_rates_with(context: WorkerContext, source: RateSource) -> date:
    """Fetch and store today's rates; never raises for an NBRB failure."""
    today = local_today(context.clock.now(), NBRB_TIMEZONE)
    try:
        rates = await source.rates_on(today)
    except RateSourceUnavailableError as exc:
        logger.warning("fx_refresh_failed", day=today.isoformat(), error=str(exc))
        return today
    if not rates:
        logger.warning("fx_refresh_not_published", day=today.isoformat())
        return today
    async with context.session_factory() as session:
        await RateService(session, source, context.clock).store(today, rates)
    logger.info("fx_refresh_stored", day=today.isoformat(), currencies=sorted(rates))
    return today
