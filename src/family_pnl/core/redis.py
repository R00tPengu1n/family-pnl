"""Async Redis client: rate limiting now, the arq job queue later."""

from pydantic import SecretStr
from redis.asyncio import Redis


def create_redis(url: SecretStr) -> "Redis":
    # Opening the client does not connect; the pool connects on first command.
    return Redis.from_url(url.get_secret_value(), decode_responses=True)
