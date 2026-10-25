"""Endpoints for the Telegram bot only, guarded by the shared bot secret (ADR-0007)."""

from fastapi import APIRouter, Depends, status

from family_pnl.api.deps import AuthServiceDep, TelegramServiceDep, require_bot
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.auth import MeResponse
from family_pnl.api.schemas.telegram import (
    BotCredentialsCodeRequest,
    BotLinkRequest,
    BotRegisterRequest,
    BotTokenRequest,
    BotTokenResponse,
    LinkCodeResponse,
)

router = APIRouter(
    tags=["bot"],
    dependencies=[Depends(require_bot)],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)


@router.post(
    "/bot/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create a Telegram-only account, as a new owner or through an invite",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register(
    body: BotRegisterRequest, telegram: TelegramServiceDep, auth: AuthServiceDep
) -> MeResponse:
    user_id = await telegram.register(
        body.telegram_id,
        display_name=body.display_name,
        household_name=body.household_name,
        invite_code=body.invite_code,
    )
    return MeResponse.of(await auth.current_user(user_id))


@router.post(
    "/bot/link",
    summary="Link a Telegram account to the user who requested the code",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def link(
    body: BotLinkRequest, telegram: TelegramServiceDep, auth: AuthServiceDep
) -> MeResponse:
    user_id = await telegram.link(body.code, body.telegram_id)
    return MeResponse.of(await auth.current_user(user_id))


@router.post(
    "/bot/credentials-code",
    status_code=status.HTTP_201_CREATED,
    summary="A one-time code (10 minutes) with which a Telegram user sets an email and password",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def credentials_code(
    body: BotCredentialsCodeRequest, telegram: TelegramServiceDep
) -> LinkCodeResponse:
    return LinkCodeResponse.of(await telegram.create_credentials_code(body.telegram_id))


@router.post(
    "/auth/telegram",
    summary="Exchange a linked Telegram id for a short-lived access token of that user",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def token(body: BotTokenRequest, telegram: TelegramServiceDep) -> BotTokenResponse:
    return BotTokenResponse.of(await telegram.issue_access_token(body.telegram_id))
