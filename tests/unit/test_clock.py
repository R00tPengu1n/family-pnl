from datetime import UTC, datetime, timedelta, timezone

import pytest

from family_pnl.core.clock import FrozenClock, SystemClock


def test_system_clock_returns_aware_utc_time() -> None:
    now = SystemClock().now()

    assert now.tzinfo is UTC


def test_frozen_clock_returns_the_same_moment_until_advanced() -> None:
    moment = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
    clock = FrozenClock(moment)

    assert clock.now() == moment
    assert clock.now() == moment


def test_frozen_clock_advances_by_a_delta() -> None:
    clock = FrozenClock(datetime(2026, 10, 31, 23, 0, tzinfo=UTC))

    clock.advance(timedelta(hours=2))

    assert clock.now() == datetime(2026, 11, 1, 1, 0, tzinfo=UTC)


def test_frozen_clock_normalises_other_time_zones_to_utc() -> None:
    minsk = timezone(timedelta(hours=3))
    clock = FrozenClock(datetime(2026, 10, 20, 12, 0, tzinfo=minsk))

    assert clock.now() == datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_frozen_clock_rejects_naive_datetime() -> None:
    naive = datetime(2026, 10, 20, 12, 0, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="time zone"):
        FrozenClock(naive)


def test_frozen_clock_can_jump_to_a_new_moment() -> None:
    clock = FrozenClock(datetime(2026, 10, 1, tzinfo=UTC))

    clock.set(datetime(2026, 10, 20, tzinfo=UTC))

    assert clock.now() == datetime(2026, 10, 20, tzinfo=UTC)
