from fastapi import APIRouter, status

from family_pnl.api.deps import AuthServiceDep, CurrentUserDep, HouseholdServiceDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.auth import MeResponse
from family_pnl.api.schemas.household import InviteResponse, MemberOut

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
