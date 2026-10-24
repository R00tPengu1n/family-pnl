from fastapi import APIRouter, status

from family_pnl.api.deps import AuthServiceDep, CurrentUserDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.auth import LoginRequest, MeResponse, RegisterRequest, TokenResponse

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
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def login(body: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    return TokenResponse.of(await auth.login(body.email, body.password))


@router.get(
    "/me",
    summary="The current user, their role and household",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse.of(user)
