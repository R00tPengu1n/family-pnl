from datetime import date
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, status

from family_pnl.api.deps import ClockDep, CurrentUserDep, RateServiceDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.common import Day
from family_pnl.api.schemas.fx import ConvertResponse, RatesResponse
from family_pnl.core.clock import Clock
from family_pnl.domain.currency import Currency
from family_pnl.domain.money import Money
from family_pnl.services.auth import CurrentUser

router = APIRouter(
    prefix="/fx",
    tags=["fx"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
)

DateQuery = Annotated[
    Day | None, Query(alias="date", description="Defaults to today in the household time zone")
]


def _day(on: date | None, user: CurrentUser, clock: Clock) -> date:
    return on or clock.now().astimezone(ZoneInfo(user.household_timezone)).date()


@router.get("/rates", summary="Official NBRB rates (BYN per unit) on a date")
async def rates(
    user: CurrentUserDep, clock: ClockDep, service: RateServiceDep, on: DateQuery = None
) -> RatesResponse:
    return RatesResponse.of(await service.rates_on(_day(on, user, clock)))


@router.get("/convert", summary="Convert an amount at the official rate of a date")
async def convert(
    user: CurrentUserDep,
    clock: ClockDep,
    service: RateServiceDep,
    amount: Annotated[Decimal, Query(ge=0, max_digits=14, decimal_places=2)],
    source: Annotated[Currency, Query(alias="from")],
    target: Annotated[Currency, Query(alias="to")],
    on: DateQuery = None,
) -> ConvertResponse:
    result = await service.rates_on(_day(on, user, clock))
    return ConvertResponse.of(Money(amount, source), target, result)
