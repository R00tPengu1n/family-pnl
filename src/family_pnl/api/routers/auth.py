from fastapi import APIRouter, Response, status

from family_pnl.api.deps import (
    AuthServiceDep,
    ClientIpDep,
    CurrentUserDep,
    SettingsServiceDep,
    TelegramServiceDep,
)
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from family_pnl.api.schemas.settings import MemberSettingsIn, MemberSettingsOut
from family_pnl.api.schemas.telegram import CredentialsRequest, LinkCodeResponse
from family_pnl.services.settings import MemberChanges

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its household",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register(body: RegisterRequest, auth: AuthServiceDep) -> MeResponse:
    user = await auth.register(body.email, body.password, body.household_name)
    return MeResponse.of(user)


@router.post(
    "/auth/login",
    summary="Exchange email and password for an access and a refresh token",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "5 failed attempts per email or per IP within 15 minutes",
        },
    },
)
async def login(body: LoginRequest, auth: AuthServiceDep, ip: ClientIpDep) -> TokenResponse:
    return TokenResponse.of(await auth.login(body.email, body.password, ip=ip))


@router.post(
    "/auth/credentials",
    summary="Set the email and password of a Telegram-only account with a code from the bot",
    responses={
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
async def set_credentials(
    body: CredentialsRequest, auth: AuthServiceDep, ip: ClientIpDep
) -> MeResponse:
    user_id = await auth.set_credentials(body.code, body.email, body.password, ip=ip)
    return MeResponse.of(await auth.current_user(user_id))


@router.post(
    "/auth/refresh",
    summary="Rotate a refresh token: the old one stops working, a new pair is returned",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def refresh(body: RefreshRequest, auth: AuthServiceDep) -> TokenResponse:
    return TokenResponse.of(await auth.refresh(body.refresh_token))


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the login session of a refresh token",
    response_class=Response,
)
async def logout(body: RefreshRequest, auth: AuthServiceDep) -> None:
    await auth.logout(body.refresh_token)


@router.get(
    "/me",
    summary="The current user, their role and household",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse.of(user)


@router.post(
    "/me/telegram-link-code",
    status_code=status.HTTP_201_CREATED,
    summary="A one-time code (10 minutes) to link this account in the Telegram bot",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def telegram_link_code(
    user: CurrentUserDep, telegram: TelegramServiceDep
) -> LinkCodeResponse:
    return LinkCodeResponse.of(await telegram.create_link_code(user))


@router.get("/me/settings", summary="Display and default input currency of the current member")
async def my_settings(user: CurrentUserDep) -> MemberSettingsOut:
    return MemberSettingsOut.of(user)


@router.patch("/me/settings", summary="Change the current member's currencies")
async def update_my_settings(
    body: MemberSettingsIn,
    user: CurrentUserDep,
    settings: SettingsServiceDep,
    auth: AuthServiceDep,
) -> MemberSettingsOut:
    sent = {name: getattr(body, name) for name in body.model_fields_set}
    await settings.update_member(user, MemberChanges(fields=sent))
    return MemberSettingsOut.of(await auth.current_user(user.id))
