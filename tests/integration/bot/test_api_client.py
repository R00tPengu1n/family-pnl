"""The bot's API client: bot-only calls, user calls with cached tokens, errors."""

import httpx
import pytest
from pydantic import SecretStr

from family_pnl_bot import api_client
from family_pnl_bot.api_client import ApiClient, ApiError, Me
from tests.integration.bot.conftest import CountingTransport, Monotonic

ANNA = 5000000001


async def test_registering_creates_an_owner_with_a_household(api: ApiClient) -> None:
    me = await api.register(ANNA, display_name="Анна")

    assert (me.display_name, me.role, me.household_name, me.email) == (
        "Анна",
        "owner",
        "Family",
        None,
    )
    assert await api.me(ANNA) == me


async def test_the_access_token_is_reused_until_shortly_before_it_expires(
    api: ApiClient, transport: CountingTransport, monotonic: Monotonic
) -> None:
    await api.register(ANNA, display_name=None)
    await api.me(ANNA)
    await api.me(ANNA)
    assert transport.paths.count("/auth/telegram") == 1

    monotonic.now += 15 * 60 - 30  # 30 seconds before the 15-minute token expires
    await api.me(ANNA)

    assert transport.paths.count("/auth/telegram") == 2


async def test_api_errors_carry_status_and_code(api: ApiClient) -> None:
    with pytest.raises(ApiError) as raised:
        await api.me(ANNA)

    assert (raised.value.status, raised.value.code, str(raised.value)) == (
        404,
        "telegram_not_registered",
        "No account is registered for this Telegram user",
    )


def client_answering(handler: httpx.MockTransport) -> ApiClient:
    http = httpx.AsyncClient(transport=handler, base_url="http://test")
    return ApiClient(http, SecretStr("s" * 32))


async def test_an_unreachable_api_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ApiError) as raised:
        await client_answering(httpx.MockTransport(refuse)).register(1, display_name=None)

    assert (raised.value.status, raised.value.code, str(raised.value)) == (
        0,
        "api_unavailable",
        "API request failed: ConnectError",
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="Bad Gateway"),
        httpx.Response(500, json={"detail": "x"}),
        httpx.Response(500, json=["error"]),
    ],
    ids=["not-json", "other-json", "a-list"],
)
async def test_an_answer_outside_the_error_format_is_unknown(response: httpx.Response) -> None:
    with pytest.raises(ApiError) as raised:
        await client_answering(httpx.MockTransport(lambda _: response)).register(
            1, display_name=None
        )

    assert (raised.value.code, str(raised.value)) == (
        "unknown",
        f"API answered HTTP {response.status_code}",
    )


async def test_an_empty_answer_is_none() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/telegram":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 900})
        assert request.headers["Authorization"] == "Bearer t"
        return httpx.Response(204)

    client = client_answering(httpx.MockTransport(respond))

    assert await client.request(1, "DELETE", "/operations/x") is None


async def test_bot_calls_identify_the_bot_and_user_calls_do_not() -> None:
    seen: list[tuple[str, str | None, str | None]] = []
    me = {
        "id": "u",
        "email": None,
        "display_name": None,
        "role": "owner",
        "household": {"name": "Family"},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.path,
                request.headers.get("X-Bot-Token"),
                request.headers.get("Authorization"),
            )
        )
        if request.url.path == "/auth/telegram":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 900})
        return httpx.Response(200, json=me)

    client = client_answering(httpx.MockTransport(respond))
    await client.me(1)

    assert seen == [("/auth/telegram", "s" * 32, None), ("/me", None, "Bearer t")]


def test_me_is_read_from_the_api_format() -> None:
    body = {
        "id": "u",
        "email": "a@example.com",
        "display_name": "Anna",
        "role": "member",
        "household": {"name": "Ivanovs", "id": "h"},
    }

    assert Me.of(body) == Me("u", "a@example.com", "Anna", "member", "Ivanovs")


def counting_api(me_statuses: list[int]) -> tuple[ApiClient, list[str]]:
    """/me answers with the given statuses in turn; every token is new."""
    seen: list[str] = []
    tokens = iter(range(100))
    me = {
        "id": "u",
        "email": None,
        "display_name": None,
        "role": "owner",
        "household": {"name": "Family"},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/telegram":
            seen.append("token")
            return httpx.Response(200, json={"access_token": f"t{next(tokens)}", "expires_in": 900})
        seen.append(request.headers["Authorization"])
        status = me_statuses.pop(0)
        if status == 401:
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "x"}})
        return httpx.Response(200, json=me)

    return client_answering(httpx.MockTransport(respond)), seen


async def test_a_refused_token_is_replaced_once() -> None:
    client, seen = counting_api([401, 200])

    me = await client.me(1)

    assert me.role == "owner"
    assert seen == ["token", "Bearer t0", "token", "Bearer t1"]


async def test_a_second_refusal_is_raised() -> None:
    client, seen = counting_api([401, 401])

    with pytest.raises(ApiError) as raised:
        await client.me(1)

    assert raised.value.status == 401
    assert seen == ["token", "Bearer t0", "token", "Bearer t1"]


async def test_the_bot_asks_for_a_credentials_code(api: ApiClient) -> None:
    await api.register(ANNA, display_name=None)

    code = await api.credentials_code(ANNA)

    assert len(code) == 9
    assert code[4] == "-"


async def test_expired_tokens_are_dropped_beyond_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_client, "SWEEP_ABOVE", 1)
    client, _ = counting_api([200, 200, 200])
    now = 0.0
    client._now = lambda: now
    await client.me(1)
    await client.me(2)
    now = 10_000.0

    await client.me(3)

    assert sorted(client._tokens) == [3]
