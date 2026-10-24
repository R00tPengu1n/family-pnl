"""The bot's API client talking to the real application in-process."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from family_pnl_bot.api_client import ApiClient
from tests.integration.conftest import BOT_SECRET


class CountingTransport(httpx.AsyncBaseTransport):
    """Forwards to the app and remembers the paths asked for."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.paths: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return await self.inner.handle_async_request(request)


class Monotonic:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def transport(app: FastAPI) -> CountingTransport:
    return CountingTransport(httpx.ASGITransport(app=app, raise_app_exceptions=False))


@pytest.fixture
def monotonic() -> Monotonic:
    return Monotonic()


@pytest.fixture
async def api(transport: CountingTransport, monotonic: Monotonic) -> AsyncIterator[ApiClient]:
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield ApiClient(http, SecretStr(BOT_SECRET), now=monotonic)
