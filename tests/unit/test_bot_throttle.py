"""Attempts per Telegram user within a sliding window."""

from family_pnl_bot.throttle import AttemptLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_attempts_are_limited_within_the_window() -> None:
    clock = Clock()
    limiter = AttemptLimiter(max_attempts=2, window_seconds=60, now=clock)

    assert [limiter.allow(1), limiter.allow(1), limiter.allow(1)] == [True, True, False]
    assert limiter.allow(2) is True  # another user has their own count


def test_attempts_leave_the_window_after_it_passes() -> None:
    clock = Clock()
    limiter = AttemptLimiter(max_attempts=2, window_seconds=60, now=clock)
    limiter.allow(1)
    clock.now += 30
    limiter.allow(1)

    clock.now += 29
    assert limiter.allow(1) is False
    clock.now += 1  # the first attempt is exactly 60 s old
    assert limiter.allow(1) is True
    assert limiter.allow(1) is False
