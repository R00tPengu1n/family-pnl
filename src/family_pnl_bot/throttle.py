"""A sliding-window limit on attempts per key, kept in the bot process."""

import time
from collections import deque
from collections.abc import Callable

# Above this many tracked users, users with no attempt left in the window are forgotten.
SWEEP_ABOVE = 1000


class AttemptLimiter:
    def __init__(
        self, max_attempts: int, window_seconds: float, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._now = now
        self._attempts: dict[int, deque[float]] = {}

    def allow(self, key: int) -> bool:
        """Count an attempt for `key`; False once the limit within the window is reached."""
        now = self._now()
        if len(self._attempts) > SWEEP_ABOVE:
            self._attempts = {
                k: v for k, v in self._attempts.items() if v and v[-1] > now - self._window
            }
        attempts = self._attempts.setdefault(key, deque())
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()
        if len(attempts) >= self._max:
            return False
        attempts.append(now)
        return True
