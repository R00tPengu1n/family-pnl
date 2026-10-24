"""Bot API client against a mocked Telegram (no network in tests)."""

import json

import httpx
import pytest
from pydantic import SecretStr

from family_pnl.integrations.telegram import (
    BotApiSender,
    TelegramChatUnavailableError,
    TelegramSendError,
    create_http_client,
)

TOKEN = "123456:secret-token"


def sender(handler: httpx.MockTransport) -> tuple[BotApiSender, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=handler, base_url="https://api.telegram.org")
    return BotApiSender(http, SecretStr(TOKEN)), http


async def test_a_message_is_posted_as_plain_text() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client, http = sender(httpx.MockTransport(respond))
    await client.send(42, "Бюджет")
    await http.aclose()

    [request] = requests
    assert (request.method, request.url.path) == ("POST", f"/bot{TOKEN}/sendMessage")
    assert json.loads(request.content) == {"chat_id": 42, "text": "Бюджет"}


@pytest.mark.parametrize("status", [400, 403])
async def test_a_chat_that_refuses_the_bot_is_not_retried(status: int) -> None:
    client, http = sender(httpx.MockTransport(lambda _: httpx.Response(status)))

    with pytest.raises(TelegramChatUnavailableError) as raised:
        await client.send(42, "x")
    await http.aclose()

    assert str(raised.value) == f"Telegram answered HTTP {status}"


@pytest.mark.parametrize("status", [429, 500, 502])
async def test_other_answers_may_pass_later(status: int) -> None:
    client, http = sender(httpx.MockTransport(lambda _: httpx.Response(status)))

    with pytest.raises(TelegramSendError) as raised:
        await client.send(42, "x")
    await http.aclose()

    assert str(raised.value) == f"Telegram answered HTTP {status}"


async def test_a_network_error_never_shows_the_token() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    client, http = sender(httpx.MockTransport(refuse))

    with pytest.raises(TelegramSendError) as raised:
        await client.send(42, "x")
    await http.aclose()

    assert str(raised.value) == "Telegram request failed: ConnectError"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


async def test_the_http_client_talks_to_the_bot_api_with_a_short_timeout() -> None:
    http = create_http_client()
    try:
        assert str(http.base_url) == "https://api.telegram.org"
        assert http.timeout == httpx.Timeout(10.0)
    finally:
        await http.aclose()
