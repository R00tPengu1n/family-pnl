"""FastAPI dependencies shared by routers."""

import hmac
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from family_pnl.core.clock import Clock
from family_pnl.core.config import Settings
from family_pnl.core.errors import AuthenticationError
from family_pnl.integrations.nbrb import NbrbClient
from family_pnl.services.accounts import AccountService
from family_pnl.services.auth import AuthService, CurrentUser
from family_pnl.services.categories import CategoryService
from family_pnl.services.fx import RateService, RateSource
from family_pnl.services.households import HouseholdService
from family_pnl.services.rate_limit import LoginRateLimiter
from family_pnl.services.telegram import TelegramService

# auto_error=False: a missing header goes through our error format, not FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from POST /auth/login")


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request; services decide when to commit."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> "Redis":
    redis: Redis = request.app.state.redis
    return redis


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated["Redis", Depends(get_redis)],
) -> AuthService:
    return AuthService(session, clock, settings, LoginRateLimiter(redis, settings))


def get_household_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> HouseholdService:
    return HouseholdService(session, clock)


def get_telegram_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TelegramService:
    return TelegramService(session, clock, settings)


class BotUnauthorizedError(AuthenticationError):
    code = "bot_unauthorized"


def require_bot(
    settings: Annotated[Settings, Depends(get_settings)],
    x_bot_token: Annotated[str | None, Header(description="Shared bot secret")] = None,
) -> None:
    """Only the bot may call; without a configured secret nobody may (ADR-0007)."""
    expected = settings.bot_api_secret
    # compare_digest takes the same time wherever the strings differ.
    if (
        expected is None
        or x_bot_token is None
        or not hmac.compare_digest(x_bot_token.encode(), expected.get_secret_value().encode())
    ):
        raise BotUnauthorizedError("Bot authentication required")


def get_rate_source(request: Request) -> RateSource:
    return NbrbClient(request.app.state.nbrb_http)


def get_rate_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    source: Annotated[RateSource, Depends(get_rate_source)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RateService:
    return RateService(session, source, clock)


def get_account_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> AccountService:
    return AccountService(session, clock)


def get_category_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CategoryService:
    return CategoryService(session, clock)


def get_client_ip(request: Request) -> str:
    # The direct peer. Behind a reverse proxy uvicorn's --proxy-headers sets it (Task 35).
    return request.client.host if request.client is not None else "unknown"


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> CurrentUser:
    if credentials is None:
        raise AuthenticationError("Authentication required")
    return await auth.authenticate(credentials.credentials)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ClientIpDep = Annotated[str, Depends(get_client_ip)]
HouseholdServiceDep = Annotated[HouseholdService, Depends(get_household_service)]
TelegramServiceDep = Annotated[TelegramService, Depends(get_telegram_service)]
ClockDep = Annotated[Clock, Depends(get_clock)]
RateServiceDep = Annotated[RateService, Depends(get_rate_service)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]
