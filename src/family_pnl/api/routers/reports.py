from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from family_pnl.api.deps import CurrentUserDep, ReportServiceDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.common import Day
from family_pnl.api.schemas.reports import ReportOut
from family_pnl.services.csv_export import report_csv, report_filename

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)


DateFrom = Annotated[Day, Query(alias="from", examples=["2026-10-01"])]
DateTo = Annotated[Day, Query(alias="to", examples=["2026-10-31"])]


@router.get("", summary="Incomes and expenses of a period in the member's display currency")
async def get_report(
    user: CurrentUserDep, reports: ReportServiceDep, date_from: DateFrom, date_to: DateTo
) -> ReportOut:
    return ReportOut.of(await reports.report(user, date_from, date_to))


@router.get(
    "/export.csv",
    response_class=Response,
    responses={status.HTTP_200_OK: {"content": {"text/csv": {}}}},
    summary="The same report as a CSV file (UTF-8 with BOM, one figure per row)",
)
async def export_report(
    user: CurrentUserDep, reports: ReportServiceDep, date_from: DateFrom, date_to: DateTo
) -> Response:
    report = await reports.report(user, date_from, date_to)
    return Response(
        content=report_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(report)}"'},
    )
