import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from family_pnl.domain.ledger import CategoryKind
from family_pnl.models import Category

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"name": "Спорт", "kind": "expense"}]}
    )

    name: CategoryName
    kind: CategoryKind


class CategoryUpdate(BaseModel):
    """Fields to change; the kind is fixed once the category exists."""

    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    archived: bool | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    kind: CategoryKind
    name: str
    default: bool
    archived: bool

    @classmethod
    def of(cls, category: Category) -> "CategoryOut":
        return cls(
            id=category.id,
            kind=category.kind,
            name=category.name,
            default=category.created_by is None,
            archived=category.archived,
        )
