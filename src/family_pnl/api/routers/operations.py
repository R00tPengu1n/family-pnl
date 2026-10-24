import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from family_pnl.api.deps import CurrentUserDep, OperationServiceDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.operations import (
    OperationCreate,
    OperationOut,
    OperationPage,
    OperationUpdate,
)
from family_pnl.domain.currency import Currency
from family_pnl.domain.ledger import OperationType
from family_pnl.repositories.ledger import OperationFilter
from family_pnl.services.operations import NewOperation, OperationChanges

router = APIRouter(
    prefix="/operations",
    tags=["operations"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Record an income or an expense",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse}},
)
async def create_operation(
    body: OperationCreate, user: CurrentUserDep, operations: OperationServiceDep
) -> OperationOut:
    new = NewOperation(**body.model_dump())
    return OperationOut.of(await operations.create(user, new))


@router.get("", summary="Operations of the household, newest first, with filters")
async def list_operations(
    user: CurrentUserDep,
    operations: OperationServiceDep,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: uuid.UUID | None = None,
    account_id: Annotated[
        uuid.UUID | None, Query(description="Either side of a transfer counts")
    ] = None,
    author_id: Annotated[uuid.UUID | None, Query(description="The member who recorded it")] = None,
    currency: Currency | None = None,
    op_type: Annotated[OperationType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperationPage:
    filters = OperationFilter(
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        account_id=account_id,
        author_id=author_id,
        currency=currency,
        type=op_type,
    )
    found, total = await operations.search(user, filters, limit=limit, offset=offset)
    return OperationPage(
        items=[OperationOut.of(op) for op in found], total=total, limit=limit, offset=offset
    )


@router.get("/{operation_id}", summary="One operation of the household")
async def get_operation(
    operation_id: uuid.UUID, user: CurrentUserDep, operations: OperationServiceDep
) -> OperationOut:
    return OperationOut.of(await operations.get(user, operation_id))


@router.patch(
    "/{operation_id}",
    summary="Change an operation (its author or the owner)",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def update_operation(
    operation_id: uuid.UUID,
    body: OperationUpdate,
    user: CurrentUserDep,
    operations: OperationServiceDep,
) -> OperationOut:
    changes = OperationChanges(**body.model_dump())
    return OperationOut.of(await operations.update(user, operation_id, changes))


@router.delete(
    "/{operation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an operation (its author or the owner)",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def delete_operation(
    operation_id: uuid.UUID, user: CurrentUserDep, operations: OperationServiceDep
) -> None:
    await operations.delete(user, operation_id)
