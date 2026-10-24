from fastapi import APIRouter, status

from family_pnl.api.deps import (
    AuthServiceDep,
    CurrentUserDep,
    HouseholdServiceDep,
    SettingsServiceDep,
)
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.auth import MeResponse
from family_pnl.api.schemas.household import InviteResponse, MemberOut
from family_pnl.api.schemas.settings import HouseholdSettingsIn, HouseholdSettingsOut
from family_pnl.services.settings import HouseholdChanges

router = APIRouter(prefix="/household", tags=["household"])


@router.post(
    "/invites",
    status_code=status.HTTP_201_CREATED,
    summary="Create a one-time invite code (owner only, valid 48 hours)",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def create_invite(user: CurrentUserDep, households: HouseholdServiceDep) -> InviteResponse:
    return InviteResponse.of(await households.create_invite(user))


@router.post(
    "/invites/{code}/redeem",
    summary="Join the household of an invite code as a member",
    responses={
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def redeem_invite(
    code: str, user: CurrentUserDep, households: HouseholdServiceDep, auth: AuthServiceDep
) -> MeResponse:
    await households.redeem_invite(user, code)
    return MeResponse.of(await auth.current_user(user.id))


@router.get("/members", summary="Members of the current household, oldest first")
async def list_members(user: CurrentUserDep, households: HouseholdServiceDep) -> list[MemberOut]:
    return [MemberOut.of(member) for member in await households.list_members(user)]


@router.get("/settings", summary="Name, base currency and time zone of the household")
async def get_settings(user: CurrentUserDep, settings: SettingsServiceDep) -> HouseholdSettingsOut:
    return HouseholdSettingsOut.of(await settings.household(user))


@router.patch(
    "/settings",
    summary="Change household settings (owner only)",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def update_settings(
    body: HouseholdSettingsIn, user: CurrentUserDep, settings: SettingsServiceDep
) -> HouseholdSettingsOut:
    changes = HouseholdChanges(
        name=body.name, base_currency=body.base_currency, timezone=body.timezone
    )
    return HouseholdSettingsOut.of(await settings.update_household(user, changes))
