"""Time source for business code.

Business code never reads the system clock directly: it receives a `Clock`, so budget
windows, token expiry and reminders are deterministic in tests.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current moment as an aware datetime in UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """A clock that stands still until moved; used in tests and simulations."""

    def __init__(self, moment: datetime) -> None:
        self._moment = _to_utc(moment)

    def now(self) -> datetime:
        return self._moment

    def set(self, moment: datetime) -> None:
        self._moment = _to_utc(moment)

    def advance(self, delta: timedelta) -> None:
        self._moment += delta


def _to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("FrozenClock needs an aware datetime with a time zone")
    return moment.astimezone(UTC)
