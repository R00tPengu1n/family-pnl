"""Typed client of the Family P&L REST API, acting for one Telegram user at a time.

The bot identifies itself with `X-Bot-Token` only to register, link and exchange a
Telegram id for that user's access token (ADR-0007); every other call carries the
user's token, so the API applies the user's own permissions. Tokens are cached until
shortly before they expire.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

# A token is renewed this many seconds before it expires.
TOKEN_MARGIN_SECONDS = 30


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True, slots=True)
class Me:
    id: str
    email: str | None
    display_name: str | None
    role: str
    household_name: str

    @classmethod
    def of(cls, body: dict[str, Any]) -> "Me":
        return cls(
            id=body["id"],
            email=body["email"],
            display_name=body["display_name"],
            role=body["role"],
            household_name=body["household"]["name"],
        )


class ApiClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        bot_secret: SecretStr,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._bot_secret = bot_secret
        self._now = now
        self._tokens: dict[int, tuple[str, float]] = {}

    async def register(
        self, telegram_id: int, *, display_name: str | None, invite_code: str | None = None
    ) -> Me:
        body = {"telegram_id": telegram_id, "display_name": display_name}
        if invite_code is not None:
            body["invite_code"] = invite_code
        return Me.of(await self._as_bot("/bot/register", body))

    async def link(self, telegram_id: int, code: str) -> Me:
        return Me.of(await self._as_bot("/bot/link", {"telegram_id": telegram_id, "code": code}))

    async def me(self, telegram_id: int) -> Me:
        return Me.of(await self.request(telegram_id, "GET", "/me"))

    async def redeem_invite(self, telegram_id: int, code: str) -> Me:
        path = f"/household/invites/{quote(code, safe='')}/redeem"
        return Me.of(await self.request(telegram_id, "POST", path))

    async def request(
        self,
        telegram_id: int,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Call the API as the user; the parsed JSON body, or None for an empty one."""
        token = await self._access_token(telegram_id)
        return await self._send(
            method, path, json=json, params=params, headers={"Authorization": f"Bearer {token}"}
        )

    async def _access_token(self, telegram_id: int) -> str:
        cached = self._tokens.get(telegram_id)
        if cached is not None and cached[1] > self._now():
            return cached[0]
        body = await self._as_bot("/auth/telegram", {"telegram_id": telegram_id})
        token: str = body["access_token"]
        valid_until = self._now() + body["expires_in"] - TOKEN_MARGIN_SECONDS
        self._tokens[telegram_id] = (token, valid_until)
        return token

    async def _as_bot(self, path: str, body: dict[str, Any]) -> Any:
        headers = {"X-Bot-Token": self._bot_secret.get_secret_value()}
        return await self._send("POST", path, json=body, params=None, headers=headers)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any,
        params: dict[str, str] | None,
        headers: dict[str, str],
    ) -> Any:
        try:
            response = await self._http.request(
                method, path, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as exc:
            message = f"API request failed: {type(exc).__name__}"
            raise ApiError(0, "api_unavailable", message) from exc
        if response.is_success:
            return response.json() if response.content else None
        code, message = _error_of(response)
        raise ApiError(response.status_code, code, message)


def _error_of(response: httpx.Response) -> tuple[str, str]:
    """The code and message of the API's error format, or a stand-in for anything else."""
    try:
        error = response.json()["error"]
        return str(error["code"]), str(error["message"])
    except (ValueError, KeyError, TypeError):
        return "unknown", f"API answered HTTP {response.status_code}"
