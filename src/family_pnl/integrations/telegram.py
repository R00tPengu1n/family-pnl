"""Sending messages through the Telegram Bot API.

`POST /bot<token>/sendMessage` with a chat id and plain text (no parse mode, so names
need no escaping). Failures are told apart by what helps:

- the chat cannot receive messages (403, or 400 "chat not found"): skip this member;
- Telegram refuses the message itself (any other 400, e.g. too long): retrying the same
  text cannot help;
- the token is refused (401, 404): nothing can be sent until the owner fixes it;
- anything else (network, 429, 5xx) may pass later.

Error messages never contain the request URL: it holds the token.
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


class TelegramMessageRejectedError(Exception):
    """Telegram refuses this message (too long, malformed); the same text never goes through."""


class TelegramTokenRejectedError(Exception):
    """The bot token is wrong or revoked: no message goes through until it is replaced."""


# 400 descriptions that are about the chat, not the message.
_CHAT_GONE = ("chat not found", "user is deactivated", "peer_id_invalid")


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
        status = response.status_code
        if status == httpx.codes.OK:
            return
        reason = f"Telegram answered HTTP {status}"
        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.NOT_FOUND):
            raise TelegramTokenRejectedError(reason)
        if status == httpx.codes.FORBIDDEN:
            raise TelegramChatUnavailableError(reason)
        if status == httpx.codes.BAD_REQUEST:
            description = _description(response)
            if any(gone in description.lower() for gone in _CHAT_GONE):
                raise TelegramChatUnavailableError(f"{reason}: {description}")
            raise TelegramMessageRejectedError(f"{reason}: {description}")
        raise TelegramSendError(reason)


def _description(response: httpx.Response) -> str:
    """Telegram's `description`, which names the problem; empty if the body has none."""
    try:
        return str(response.json().get("description", ""))
    except (ValueError, AttributeError):
        return ""


def create_http_client(base_url: str = BASE_URL) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0), verify=tls_context())
