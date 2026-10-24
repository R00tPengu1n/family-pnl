import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from family_pnl.api.deps import BudgetServiceDep, CurrentUserDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.budgets import BudgetOut, LimitIn

router = APIRouter(
    prefix="/budgets",
    tags=["budgets"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)

MonthPath = Annotated[
    str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM", examples=["2026-11"])
]


def _first_day(month: str) -> date:
    year, number = month.split("-")
    return date(int(year), int(number), 1)


@router.get("/{month}", summary="The budget of a month (an empty draft if none yet)")
async def get_budget(
    month: MonthPath, user: CurrentUserDep, budgets: BudgetServiceDep
) -> BudgetOut:
    return BudgetOut.of(await budgets.view(user, _first_day(month)))


@router.put(
    "/{month}/limits/{category_id}",
    summary="Set the limit of an expense category (members inside the window, the owner always)",
)
async def set_limit(
    month: MonthPath,
    category_id: uuid.UUID,
    body: LimitIn,
    user: CurrentUserDep,
    budgets: BudgetServiceDep,
) -> BudgetOut:
    view = await budgets.set_limit(user, _first_day(month), category_id, body.amount)
    return BudgetOut.of(view)


@router.delete(
    "/{month}/limits/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove the limit of a category",
)
async def remove_limit(
    month: MonthPath, category_id: uuid.UUID, user: CurrentUserDep, budgets: BudgetServiceDep
) -> None:
    await budgets.remove_limit(user, _first_day(month), category_id)


@router.post("/{month}/approve", summary="Approve the budget (owner only)")
async def approve(month: MonthPath, user: CurrentUserDep, budgets: BudgetServiceDep) -> BudgetOut:
    return BudgetOut.of(await budgets.approve(user, _first_day(month)))
