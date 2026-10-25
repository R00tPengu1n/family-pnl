"""Failed-login counters in Redis, per email and per IP (fixed window).

Every attempt is counted before the password is checked, atomically; a successful login
takes its attempt back. The first attempt starts a window (`login_failure_window`); once
`login_max_failures` attempts have failed, further logins for that email or from that IP
are refused until the window expires. Emails are stored as SHA-256 digests.

If Redis is unavailable the limiter fails open and logs a warning (ADR-0006): an outage of
the cache must not lock every user out.
"""

import hashlib

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from family_pnl.core.config import Settings
from family_pnl.core.errors import RateLimitedError
from family_pnl.domain.identity import normalize_email

logger = structlog.get_logger(__name__)


class LoginRateLimiter:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._max_failures = settings.login_max_failures
        self._window_seconds = settings.login_failure_window_seconds

    async def reserve(self, email: str, ip: str) -> None:
        """Count this attempt, then raise RateLimitedError if it is over the limit.

        The attempt is counted before the password is checked, in one atomic step, so
        parallel attempts cannot all pass a check made before any of them was counted.
        """
        keys = [_email_key(email), _ip_key(ip)]
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                for key in keys:
                    pipe.incr(key)
                    # NX: only the first attempt sets the expiry, so the window is fixed.
                    pipe.expire(key, self._window_seconds, nx=True)
                results = await pipe.execute()
            blocked = [
                key
                for key, count in zip(keys, results[::2], strict=True)
                if int(count) > self._max_failures
            ]
            if not blocked:
                return
            ttls = [await self._redis.ttl(key) for key in blocked]
        except (RedisError, OSError) as exc:
            _unavailable(exc)
            return
        retry_after = max((ttl for ttl in ttls if ttl > 0), default=self._window_seconds)
        raise RateLimitedError("Too many failed login attempts", retry_after=retry_after)

    async def succeeded(self, email: str, ip: str) -> None:
        """A successful login is not a failure: forget the email's, give back the IP's."""
        try:
            await self._redis.delete(_email_key(email))
            await self._redis.eval(_GIVE_BACK, 1, _ip_key(ip))
        except (RedisError, OSError) as exc:
            _unavailable(exc)


# DECR only a live counter: a missing key would become -1 with no expiry.
_GIVE_BACK = """
if redis.call('exists', KEYS[1]) == 1 then
    return redis.call('decr', KEYS[1])
end
return 0
"""


def _email_key(email: str) -> str:
    digest = hashlib.sha256(normalize_email(email).encode()).hexdigest()
    return f"login:fail:email:{digest}"


def _ip_key(ip: str) -> str:
    return f"login:fail:ip:{ip}"


def _unavailable(exc: Exception) -> None:
    logger.warning("rate_limit_unavailable", error=type(exc).__name__)
