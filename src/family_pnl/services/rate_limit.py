"""Failed-login counters in Redis, per email and per IP (fixed window).

The first failure starts a window (`login_failure_window`); once a counter reaches
`login_max_failures`, further logins for that email or from that IP are refused until the
window expires. Emails are stored as SHA-256 digests, not in plain text.

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
    def __init__(self, redis: "Redis", settings: Settings) -> None:
        self._redis = redis
        self._max_failures = settings.login_max_failures
        self._window_seconds = settings.login_failure_window_seconds

    async def check(self, email: str, ip: str) -> None:
        """Raise RateLimitedError if the email or the IP has used up its failures."""
        keys = [_email_key(email), _ip_key(ip)]
        try:
            counts = await self._redis.mget(keys)
            blocked = [
                key
                for key, count in zip(keys, counts, strict=True)
                if count is not None and int(count) >= self._max_failures
            ]
            if not blocked:
                return
            ttls = [await self._redis.ttl(key) for key in blocked]
        except (RedisError, OSError) as exc:
            _unavailable(exc)
            return
        retry_after = max((ttl for ttl in ttls if ttl > 0), default=self._window_seconds)
        raise RateLimitedError("Too many failed login attempts", retry_after=retry_after)

    async def record_failure(self, email: str, ip: str) -> None:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                for key in (_email_key(email), _ip_key(ip)):
                    pipe.incr(key)
                    # NX: only the first failure sets the expiry, so the window is fixed.
                    pipe.expire(key, self._window_seconds, nx=True)
                await pipe.execute()
        except (RedisError, OSError) as exc:
            _unavailable(exc)

    async def reset_email(self, email: str) -> None:
        """Forget an email's failures after a successful login; the IP counter stays."""
        try:
            await self._redis.delete(_email_key(email))
        except (RedisError, OSError) as exc:
            _unavailable(exc)


def _email_key(email: str) -> str:
    digest = hashlib.sha256(normalize_email(email).encode()).hexdigest()
    return f"login:fail:email:{digest}"


def _ip_key(ip: str) -> str:
    return f"login:fail:ip:{ip}"


def _unavailable(exc: Exception) -> None:
    logger.warning("rate_limit_unavailable", error=type(exc).__name__)
