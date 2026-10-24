import uuid

import pytest

from family_pnl.core.errors import PermissionDeniedError
from family_pnl.domain.identity import Role
from family_pnl.domain.ledger import (
    DEFAULT_CATEGORIES,
    AccountType,
    CategoryKind,
    category_key,
    require_category_editor,
)

ANNA = uuid.uuid4()
IVAN = uuid.uuid4()


def test_account_types_and_category_kinds_have_stable_values() -> None:
    assert [t.value for t in AccountType] == ["card", "cash", "savings"]
    assert [k.value for k in CategoryKind] == ["income", "expense"]


def test_the_default_set_has_expense_and_income_categories() -> None:
    assert DEFAULT_CATEGORIES == (
        (CategoryKind.EXPENSE, "Продукты"),
        (CategoryKind.EXPENSE, "Кафе и рестораны"),
        (CategoryKind.EXPENSE, "Транспорт"),
        (CategoryKind.EXPENSE, "Жильё и коммунальные"),
        (CategoryKind.EXPENSE, "Связь и интернет"),
        (CategoryKind.EXPENSE, "Здоровье"),
        (CategoryKind.EXPENSE, "Одежда"),
        (CategoryKind.EXPENSE, "Дети"),
        (CategoryKind.EXPENSE, "Развлечения"),
        (CategoryKind.EXPENSE, "Подарки"),
        (CategoryKind.EXPENSE, "Другое"),
        (CategoryKind.INCOME, "Зарплата"),
        (CategoryKind.INCOME, "Подработка"),
        (CategoryKind.INCOME, "Подарки"),
        (CategoryKind.INCOME, "Другое"),
    )


def test_default_names_are_unique_within_each_kind() -> None:
    keys = [(kind, category_key(name)) for kind, name in DEFAULT_CATEGORIES]

    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("name", "key"),
    [("Кафе", "кафе"), ("  КАФЕ ", "кафе"), ("Taxi", "taxi"), ("Ёлка", "ёлка")],
)
def test_category_names_compare_case_insensitively_and_trimmed(name: str, key: str) -> None:
    assert category_key(name) == key


@pytest.mark.parametrize(
    ("actor", "role", "created_by", "allowed"),
    [
        (ANNA, Role.MEMBER, ANNA, True),
        (IVAN, Role.MEMBER, ANNA, False),
        (IVAN, Role.OWNER, ANNA, True),
        (ANNA, Role.MEMBER, None, False),  # a default category
        (IVAN, Role.OWNER, None, True),
    ],
    ids=["author", "other-member", "owner", "member-on-default", "owner-on-default"],
)
def test_who_may_change_a_category(
    actor: uuid.UUID, role: Role, created_by: uuid.UUID | None, allowed: bool
) -> None:
    if allowed:
        require_category_editor(actor_id=actor, role=role, created_by=created_by)
    else:
        with pytest.raises(PermissionDeniedError) as info:
            require_category_editor(actor_id=actor, role=role, created_by=created_by)
        assert (
            info.value.message == "Only its author or the household owner can change this category"
        )
