"""The daily NBRB rate refresh job, its worker context and the worker settings."""

import dataclasses
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from family_pnl.core.clock import FrozenClock
from family_pnl.core.config import Settings
from family_pnl.domain.currency import Currency
from family_pnl.repositories.fx import FxRateRepository
from family_pnl.worker import context as worker_context
from family_pnl.worker import settings as worker_settings_module
from family_pnl.worker.context import WorkerContext, build_context, context_of, shutdown, startup
from family_pnl.worker.jobs.fx import refresh_rates, refresh_rates_with
from tests.integration.test_rate_service import RATES_TUESDAY, FakeSource

# 21:30 UTC on 19 October is 00:30 on 20 October in Minsk.
NOW = datetime(2026, 10, 19, 21, 30, tzinfo=UTC)
MINSK_TODAY = date(2026, 10, 20)
NBRB_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "nbrb" / "rates_2026-10-20.json"


@pytest.fixture
async def context(settings: Settings, db_session: AsyncSession) -> AsyncIterator[WorkerContext]:
    """A worker context whose sessions live inside the test transaction."""
    built = build_context(settings, FrozenClock(NOW))
    factory = async_sessionmaker(
        bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield dataclasses.replace(built, session_factory=factory)
    await built.close()


async def stored(db_session: AsyncSession, day: date) -> dict[Currency, str]:
    rows = await FxRateRepository(db_session).on_date(day)
    return {currency: str(row.byn_per_unit) for currency, row in rows.items()}


async def test_the_job_stores_the_rates_of_today_in_minsk(
    context: WorkerContext, db_session: AsyncSession
) -> None:
    source = FakeSource({MINSK_TODAY: RATES_TUESDAY})

    with structlog.testing.capture_logs() as logs:
        day = await refresh_rates_with(context, source)

    assert day == MINSK_TODAY
    assert source.calls == [MINSK_TODAY]
    assert await stored(db_session, MINSK_TODAY) == {
        Currency.USD: "2.99500000",
        Currency.RUB: "0.03612700",
    }
    assert {"event": "fx_refresh_stored", "day": "2026-10-20", "currencies": ["RUB", "USD"]} in [
        {k: v for k, v in log.items() if k != "log_level"} for log in logs
    ]


async def test_running_twice_a_day_keeps_one_rate_per_currency(
    context: WorkerContext, db_session: AsyncSession
) -> None:
    source = FakeSource({MINSK_TODAY: RATES_TUESDAY})
    await refresh_rates_with(context, source)

    await refresh_rates_with(context, source)

    rows = await FxRateRepository(db_session).on_date(MINSK_TODAY)
    assert sorted(rows) == [Currency.RUB, Currency.USD]


async def test_an_nbrb_failure_is_logged_and_not_raised(
    context: WorkerContext, db_session: AsyncSession
) -> None:
    source = FakeSource({MINSK_TODAY: RATES_TUESDAY})
    source.down = True

    with structlog.testing.capture_logs() as logs:
        await refresh_rates_with(context, source)

    assert await stored(db_session, MINSK_TODAY) == {}
    assert [(log["event"], log["log_level"]) for log in logs] == [("fx_refresh_failed", "warning")]


async def test_rates_not_published_yet_are_logged(
    context: WorkerContext, db_session: AsyncSession
) -> None:
    with structlog.testing.capture_logs() as logs:
        await refresh_rates_with(context, FakeSource({}))

    assert await stored(db_session, MINSK_TODAY) == {}
    assert [(log["event"], log["day"]) for log in logs] == [
        ("fx_refresh_not_published", "2026-10-20")
    ]


async def test_the_cron_job_asks_nbrb_through_the_shared_http_client(
    context: WorkerContext, db_session: AsyncSession
) -> None:
    requested: list[str] = []

    def nbrb(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url.params["ondate"]))
        return httpx.Response(200, content=NBRB_FIXTURE.read_bytes())

    await context.nbrb_http.aclose()
    http = httpx.AsyncClient(base_url="https://nbrb.test", transport=httpx.MockTransport(nbrb))
    ctx = {worker_context.CONTEXT_KEY: dataclasses.replace(context, nbrb_http=http)}

    await refresh_rates(ctx)

    await http.aclose()
    assert requested == ["2026-10-20"]
    assert set(await stored(db_session, MINSK_TODAY)) == {Currency.USD, Currency.RUB}


async def test_startup_builds_the_context_and_shutdown_closes_it(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_context, "get_settings", lambda: settings)
    ctx: dict[str, object] = {}

    await startup(ctx)
    context = context_of(ctx)
    await shutdown(ctx)

    assert context.settings is settings
    assert context.nbrb_http.is_closed


def test_worker_settings_come_from_the_configuration(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_settings_module, "get_settings", lambda: settings)

    found = worker_settings_module.WorkerSettings

    redis_url = settings.redis_url.get_secret_value()
    assert (found["redis_settings"].host, found["redis_settings"].database) == (
        "127.0.0.1",
        int(redis_url.rsplit("/", 1)[1]),
    )
    assert (found["on_startup"], found["on_shutdown"], found["timezone"]) == (
        startup,
        shutdown,
        UTC,
    )
    [job] = found["cron_jobs"]
    assert (job.name, job.hour, job.minute, job.unique) == (
        "cron:refresh_rates",
        {21, 6},
        10,
        True,
    )


def test_other_names_are_not_in_the_settings_module() -> None:
    with pytest.raises(AttributeError, match="has no attribute 'Missing'"):
        _ = worker_settings_module.Missing
