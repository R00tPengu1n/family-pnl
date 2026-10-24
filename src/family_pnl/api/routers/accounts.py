import uuid

from fastapi import APIRouter, status

from family_pnl.api.deps import AccountServiceDep, BalanceServiceDep, CurrentUserDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.accounts import (
    AccountBalanceOut,
    AccountCreate,
    AccountOut,
    AccountUpdate,
)
from family_pnl.services.accounts import AccountChanges

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a personal account, or a shared one (owner only)",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def create_account(
    body: AccountCreate, user: CurrentUserDep, accounts: AccountServiceDep
) -> AccountOut:
    account = await accounts.create(
        user, name=body.name, account_type=body.type, currency=body.currency, shared=body.shared
    )
    return AccountOut.of(account)


@router.get("", summary="Accounts of the household, by name")
async def list_accounts(
    user: CurrentUserDep, accounts: AccountServiceDep, include_archived: bool = False
) -> list[AccountOut]:
    found = await accounts.list(user, include_archived=include_archived)
    return [AccountOut.of(account) for account in found]


# Registered before /{account_id}: otherwise "balances" is parsed as an account id.
@router.get(
    "/balances",
    summary="Balance of every account in its own currency",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
)
async def list_balances(
    user: CurrentUserDep, balances: BalanceServiceDep, include_archived: bool = False
) -> list[AccountBalanceOut]:
    found = await balances.balances(user, include_archived=include_archived)
    return [AccountBalanceOut.of(item) for item in found]


@router.get(
    "/{account_id}",
    summary="One account of the household",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_account(
    account_id: uuid.UUID, user: CurrentUserDep, accounts: AccountServiceDep
) -> AccountOut:
    return AccountOut.of(await accounts.get(user, account_id))


@router.patch(
    "/{account_id}",
    summary="Rename, retype or archive an account (its holder or the owner)",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def update_account(
    account_id: uuid.UUID, body: AccountUpdate, user: CurrentUserDep, accounts: AccountServiceDep
) -> AccountOut:
    changes = AccountChanges(name=body.name, type=body.type, archived=body.archived)
    return AccountOut.of(await accounts.update(user, account_id, changes))
