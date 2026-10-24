import uuid

from fastapi import APIRouter, status

from family_pnl.api.deps import CategoryServiceDep, CurrentUserDep
from family_pnl.api.errors import ErrorResponse
from family_pnl.api.schemas.categories import CategoryCreate, CategoryOut, CategoryUpdate
from family_pnl.domain.ledger import CategoryKind
from family_pnl.services.categories import CategoryChanges

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)


@router.get("", summary="Categories of the household, by kind and name")
async def list_categories(
    user: CurrentUserDep,
    categories: CategoryServiceDep,
    kind: CategoryKind | None = None,
    include_archived: bool = False,
) -> list[CategoryOut]:
    found = await categories.list(user, kind=kind, include_archived=include_archived)
    return [CategoryOut.of(category) for category in found]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Add a category (any member)",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def create_category(
    body: CategoryCreate, user: CurrentUserDep, categories: CategoryServiceDep
) -> CategoryOut:
    return CategoryOut.of(await categories.create(user, name=body.name, kind=body.kind))


@router.patch(
    "/{category_id}",
    summary="Rename or archive a category (its author or the owner)",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdate,
    user: CurrentUserDep,
    categories: CategoryServiceDep,
) -> CategoryOut:
    changes = CategoryChanges(name=body.name, archived=body.archived)
    return CategoryOut.of(await categories.update(user, category_id, changes))
