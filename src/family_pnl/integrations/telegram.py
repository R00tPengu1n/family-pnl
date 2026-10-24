"""Sending messages through the Telegram Bot API.

`POST /bot<token>/sendMessage` with a chat id and plain text (no parse mode, so names
need no escaping). Failures are split in two: a chat that cannot receive messages (the
user blocked the bot, the chat is gone) will not get better by retrying; anything else
(network, 429, 5xx) may. Error messages never contain the request URL: it holds the token.
"""

from typing import Protocol

import httpx
from pydantic import SecretStr

from family_pnl.integrations.tls import tls_context

BASE_URL = "https://api.telegram.org"


class TelegramSendError(Exception):
    """The message may go through later: network trouble, rate limit, server error."""


class TelegramChatUnavailableError(Exception):
    """This chat does not accept messages from the bot; retrying will not help."""


class TelegramSender(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


class BotApiSender:
    def __init__(self, http: httpx.AsyncClient, token: SecretStr) -> None:
        self._http = http
        self._token = token

    async def send(self, chat_id: int, text: str) -> None:
        try:
            response = await self._http.post(
                f"/bot{self._token.get_secret_value()}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        except httpx.HTTPError as exc:
            raise TelegramSendError(f"Telegram request failed: {type(exc).__name__}") from None
        if response.status_code in (httpx.codes.BAD_REQUEST, httpx.codes.FORBIDDEN):
            raise TelegramChatUnavailableError(f"Telegram answered HTTP {response.status_code}")
        if response.status_code != httpx.codes.OK:
            raise TelegramSendError(f"Telegram answered HTTP {response.status_code}")


def create_http_client(base_url: str = BASE_URL) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0), verify=tls_context())
