"""arq worker: `uv run arq family_pnl.worker.settings.WorkerSettings` (ADR-0001).

`WorkerSettings` is built on first access rather than at import, so importing this module
needs no configuration; arq accepts a dict of worker options as well as a class.
"""

import datetime
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from family_pnl.core.config import Settings, get_settings
from family_pnl.worker.context import shutdown, startup
from family_pnl.worker.jobs.budgets import send_budget_reminders
from family_pnl.worker.jobs.fx import refresh_rates
from family_pnl.worker.jobs.notifications import deliver_notifications


def worker_settings(settings: Settings) -> dict[str, Any]:
    return {
        "redis_settings": RedisSettings.from_dsn(settings.redis_url.get_secret_value()),
        "on_startup": startup,
        "on_shutdown": shutdown,
        # Cron times are UTC. 21:10 and 06:10 UTC are 00:10 and 09:10 in Minsk (UTC+3 all
        # year): NBRB sets the rates the day before; the second run covers a failed first.
        "timezone": datetime.UTC,
        "cron_jobs": [
            cron(refresh_rates, hour={21, 6}, minute=10, unique=True),
            cron(deliver_notifications, second=0, unique=True),  # every minute
            # Hourly, because households live in different time zones (09:00 local).
            cron(send_budget_reminders, minute=5, unique=True),
        ],
    }


def __getattr__(name: str) -> Any:
    if name == "WorkerSettings":
        return worker_settings(get_settings())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
