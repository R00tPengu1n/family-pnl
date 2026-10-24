"""Income and expense categories of a household."""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from family_pnl.core.clock import Clock
from family_pnl.core.errors import ConflictError, NotFoundError
from family_pnl.domain.ledger import CategoryKind, category_key, require_category_editor
from family_pnl.models import Category
from family_pnl.repositories.ledger import CategoryRepository
from family_pnl.services.auth import CurrentUser


class CategoryNotFoundError(NotFoundError):
    pass


class CategoryExistsError(ConflictError):
    code = "category_exists"


@dataclass(frozen=True, slots=True)
class CategoryChanges:
    name: str | None = None
    archived: bool | None = None


class CategoryService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._categories = CategoryRepository(session)

    async def list(
        self, user: CurrentUser, *, kind: CategoryKind | None, include_archived: bool
    ) -> list[Category]:
        return await self._categories.list(
            user.household_id, kind=kind, include_archived=include_archived
        )

    async def create(self, user: CurrentUser, *, name: str, kind: CategoryKind) -> Category:
        await self._ensure_free(user.household_id, kind, name)
        category = Category(
            id=uuid.uuid4(),
            household_id=user.household_id,
            kind=kind,
            name=name,
            name_key=category_key(name),
            archived=False,
            created_by=user.id,
            created_at=self._clock.now(),
        )
        self._categories.add_all([category])
        await self._commit()
        return category

    async def update(
        self, user: CurrentUser, category_id: uuid.UUID, changes: CategoryChanges
    ) -> Category:
        category = await self._categories.get(user.household_id, category_id)
        if category is None:
            raise CategoryNotFoundError("Category not found")
        require_category_editor(actor_id=user.id, role=user.role, created_by=category.created_by)
        if changes.name is not None and category_key(changes.name) != category.name_key:
            await self._ensure_free(user.household_id, category.kind, changes.name)
            category.name_key = category_key(changes.name)
        if changes.name is not None:
            category.name = changes.name
        if changes.archived is not None:
            category.archived = changes.archived
        await self._commit()
        return category

    async def _ensure_free(self, household_id: uuid.UUID, kind: CategoryKind, name: str) -> None:
        if await self._categories.name_taken(household_id, kind, category_key(name)):
            raise CategoryExistsError("A category with this name already exists")

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # Two requests created the same name between the check and the commit.
            await self._session.rollback()
            raise CategoryExistsError("A category with this name already exists") from exc
