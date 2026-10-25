"""Bot API client against a mocked Telegram (no network in tests)."""

import json

import httpx
import pytest
from pydantic import SecretStr

from family_pnl.integrations.telegram import (
    BotApiSender,
    TelegramChatUnavailableError,
    TelegramMessageRejectedError,
    TelegramSendError,
    TelegramTokenRejectedError,
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


def answering(status: int, description: str | None = None) -> httpx.MockTransport:
    body = {"ok": False, "description": description} if description is not None else None
    return httpx.MockTransport(lambda _: httpx.Response(status, json=body))


async def failure_of(transport: httpx.MockTransport) -> Exception:
    client, http = sender(transport)
    try:
        await client.send(42, "x")
    except Exception as exc:
        return exc
    finally:
        await http.aclose()
    raise AssertionError("the send did not fail")


@pytest.mark.parametrize(
    ("status", "description", "text"),
    [
        (403, "Forbidden: bot was blocked by the user", "Telegram answered HTTP 403"),
        (
            400,
            "Bad Request: chat not found",
            "Telegram answered HTTP 400: Bad Request: chat not found",
        ),
        (
            400,
            "Bad Request: user is deactivated",
            "Telegram answered HTTP 400: Bad Request: user is deactivated",
        ),
        (
            400,
            "Bad Request: PEER_ID_INVALID",
            "Telegram answered HTTP 400: Bad Request: PEER_ID_INVALID",
        ),
    ],
)
async def test_a_chat_that_cannot_receive_is_not_retried(
    status: int, description: str, text: str
) -> None:
    error = await failure_of(answering(status, description))

    assert isinstance(error, TelegramChatUnavailableError)
    assert str(error) == text


@pytest.mark.parametrize(
    ("description", "text"),
    [
        (
            "Bad Request: message is too long",
            "Telegram answered HTTP 400: Bad Request: message is too long",
        ),
        (None, "Telegram answered HTTP 400: "),
    ],
    ids=["too-long", "no-description"],
)
async def test_a_message_telegram_refuses_is_not_a_chat_problem(
    description: str | None, text: str
) -> None:
    error = await failure_of(answering(400, description))

    assert isinstance(error, TelegramMessageRejectedError)
    assert str(error) == text


async def test_a_400_without_a_json_body_is_a_refused_message() -> None:
    error = await failure_of(httpx.MockTransport(lambda _: httpx.Response(400, text="oops")))

    assert isinstance(error, TelegramMessageRejectedError)


@pytest.mark.parametrize("status", [401, 404])
async def test_a_refused_token_stops_everything(status: int) -> None:
    error = await failure_of(answering(status, "Unauthorized"))

    assert isinstance(error, TelegramTokenRejectedError)
    assert str(error) == f"Telegram answered HTTP {status}"


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
