import uuid

from fastapi import APIRouter, Response, status

from family_pnl.api.deps import CurrentUserDep, OperationServiceDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.operations import OperationCreate, OperationOut, OperationUpdate
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
