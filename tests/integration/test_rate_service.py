"""RateService: stored rates first, NBRB on demand, nearest earlier and last known fallbacks."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import FrozenClock
from family_pnl.domain.currency import Currency
from family_pnl.domain.money import Money
from family_pnl.integrations.nbrb import RateSourceUnavailableError
from family_pnl.models import FxRate
from family_pnl.services.fx import RateService, RatesOnDate, RatesUnavailableError

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)
RATES_MONDAY = {Currency.USD: Decimal("2.9910"), Currency.RUB: Decimal("0.036080")}
RATES_TUESDAY = {Currency.USD: Decimal("2.9950"), Currency.RUB: Decimal("0.036127")}


class FakeSource:
    """Stands in for NBRB: answers from a dict and records every request."""

    def __init__(self, published: dict[date, dict[Currency, Decimal]]) -> None:
        self.published = published
        self.calls: list[date] = []
        self.down = False

    async def rates_on(self, day: date) -> dict[Currency, Decimal]:
        self.calls.append(day)
        if self.down:
            raise RateSourceUnavailableError("NBRB request failed: ConnectError")
        return dict(self.published.get(day, {}))


@pytest.fixture
def source() -> FakeSource:
    return FakeSource({MONDAY: RATES_MONDAY, TUESDAY: RATES_TUESDAY})


@pytest.fixture
def service(db_session: AsyncSession, source: FakeSource, clock: FrozenClock) -> RateService:
    return RateService(db_session, source, clock)


def summary(result: RatesOnDate) -> dict[Currency, tuple[Decimal, date]]:
    return {q.currency: (q.byn_per_unit, q.rate_date) for q in result.quotes.values()}


async def stored_rows(db_session: AsyncSession) -> int:
    return await db_session.scalar(select(func.count()).select_from(FxRate)) or 0


async def test_a_missing_date_is_fetched_once_and_stored(
    service: RateService, source: FakeSource, db_session: AsyncSession
) -> None:
    first = await service.rates_on(TUESDAY)
    second = await service.rates_on(TUESDAY)

    assert source.calls == [TUESDAY]
    assert (
        summary(first)
        == summary(second)
        == {
            Currency.USD: (Decimal("2.9950"), TUESDAY),
            Currency.RUB: (Decimal("0.036127"), TUESDAY),
        }
    )
    assert await stored_rows(db_session) == 2


async def test_stored_rates_keep_eight_decimal_places(
    service: RateService, db_session: AsyncSession
) -> None:
    await service.rates_on(TUESDAY)

    stored = await db_session.scalar(select(FxRate).where(FxRate.currency == Currency.RUB))

    assert stored is not None
    assert stored.byn_per_unit == Decimal("0.036127")


async def test_result_converts_through_byn(service: RateService) -> None:
    result = await service.rates_on(TUESDAY)

    usd = Money(Decimal("100"), Currency.USD)

    assert result.convert(usd, Currency.RUB).rounded() == Money(Decimal("8290.20"), Currency.RUB)


async def test_an_unpublished_date_uses_the_nearest_earlier_stored_rate(
    service: RateService, source: FakeSource, db_session: AsyncSession
) -> None:
    await service.rates_on(MONDAY)
    future = TUESDAY + timedelta(days=30)
    source.published.pop(TUESDAY)

    result = await service.rates_on(future)

    assert result.requested == future
    assert summary(result)[Currency.USD] == (Decimal("2.9910"), MONDAY)
    # The fallback is not stored under the future date: the real rate can still arrive.
    assert await stored_rows(db_session) == 2


async def test_an_unpublished_date_with_nothing_stored_walks_back_to_a_published_day(
    service: RateService, source: FakeSource
) -> None:
    thursday = TUESDAY + timedelta(days=2)

    result = await service.rates_on(thursday)

    assert summary(result)[Currency.USD] == (Decimal("2.9950"), TUESDAY)
    assert source.calls == [thursday, thursday - timedelta(days=1), TUESDAY]


async def test_walking_back_stops_after_a_week(service: RateService, source: FakeSource) -> None:
    far_future = TUESDAY + timedelta(days=60)

    with pytest.raises(RatesUnavailableError) as info:
        await service.rates_on(far_future)

    assert len(source.calls) == 8  # the day itself and seven days back
    assert info.value.code == "rates_unavailable"


async def test_when_nbrb_is_down_the_last_known_rate_is_used_with_a_warning(
    service: RateService, source: FakeSource
) -> None:
    await service.rates_on(MONDAY)
    source.down = True

    with structlog.testing.capture_logs() as logs:
        result = await service.rates_on(TUESDAY)

    assert summary(result)[Currency.RUB] == (Decimal("0.036080"), MONDAY)
    assert logs == [
        {
            "event": "fx_rate_source_unavailable",
            "requested": "2026-10-20",
            "error": "NBRB request failed: ConnectError",
            "log_level": "warning",
        }
    ]


async def test_when_nbrb_is_down_and_nothing_is_known_rates_are_unavailable(
    service: RateService, source: FakeSource
) -> None:
    source.down = True

    with pytest.raises(RatesUnavailableError):
        await service.rates_on(TUESDAY)


async def test_stored_rates_need_no_call_to_nbrb(service: RateService, source: FakeSource) -> None:
    await service.rates_on(TUESDAY)
    source.down = True

    result = await service.rates_on(TUESDAY)

    assert summary(result)[Currency.USD] == (Decimal("2.9950"), TUESDAY)
    assert source.calls == [TUESDAY]


async def test_storing_a_rate_that_already_exists_is_not_an_error(
    db_session: AsyncSession, clock: FrozenClock
) -> None:
    # Two requests for one new date race: both fetch and both insert.
    first = RateService(db_session, FakeSource({TUESDAY: RATES_TUESDAY}), clock)
    await first.store(TUESDAY, RATES_TUESDAY)

    await first.store(TUESDAY, RATES_TUESDAY)

    assert await stored_rows(db_session) == 2


async def test_a_partial_answer_fills_the_gap_from_the_nearest_earlier_rate(
    service: RateService, source: FakeSource
) -> None:
    await service.rates_on(MONDAY)
    source.published[TUESDAY] = {Currency.USD: Decimal("2.9950")}

    result = await service.rates_on(TUESDAY)

    assert summary(result) == {
        Currency.USD: (Decimal("2.9950"), TUESDAY),
        Currency.RUB: (Decimal("0.036080"), MONDAY),
    }


class FailsAfterFirstCall(FakeSource):
    """Answers the first request (nothing published), then goes down."""

    async def rates_on(self, day: date) -> dict[Currency, Decimal]:
        if self.calls:
            self.down = True
        return await super().rates_on(day)


async def test_nbrb_failing_while_walking_back_means_rates_are_unavailable(
    db_session: AsyncSession, clock: FrozenClock
) -> None:
    flaky = FailsAfterFirstCall({TUESDAY: RATES_TUESDAY})
    service = RateService(db_session, flaky, clock)

    with structlog.testing.capture_logs() as logs, pytest.raises(RatesUnavailableError):
        await service.rates_on(TUESDAY + timedelta(days=2))

    assert [log["event"] for log in logs] == ["fx_rate_source_unavailable"]


async def test_nbrb_down_keeps_the_stored_part_and_fills_the_rest_from_earlier(
    service: RateService, source: FakeSource
) -> None:
    await service.rates_on(MONDAY)
    await service.store(TUESDAY, {Currency.USD: Decimal("2.9950")})
    source.down = True

    result = await service.rates_on(TUESDAY)

    assert summary(result) == {
        Currency.USD: (Decimal("2.9950"), TUESDAY),
        Currency.RUB: (Decimal("0.036080"), MONDAY),
    }


async def test_a_rate_seven_days_back_is_still_found(
    db_session: AsyncSession, clock: FrozenClock
) -> None:
    source = FakeSource({TUESDAY: RATES_TUESDAY})
    service = RateService(db_session, source, clock)

    result = await service.rates_on(TUESDAY + timedelta(days=7))

    assert summary(result)[Currency.USD] == (Decimal("2.9950"), TUESDAY)
    assert len(source.calls) == 8


async def test_fetching_rates_leaves_the_callers_transaction_to_the_caller(
    service: RateService, db_session: AsyncSession
) -> None:
    # An expense looks up rates for its budget check: committing there would commit the
    # expense before its notification is written (ADR-0009).
    await service.rates_on(TUESDAY)
    assert await stored_rows(db_session) == 2

    await db_session.rollback()

    assert await stored_rows(db_session) == 0
