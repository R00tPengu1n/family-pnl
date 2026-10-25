import uuid
from datetime import date

import pytest

from family_pnl.core.errors import PermissionDeniedError, ValidationFailedError
from family_pnl.domain.identity import Role
from family_pnl.domain.ledger import (
    DEFAULT_CATEGORIES,
    EARLIEST_DATE,
    LATEST_DATE,
    AccountType,
    CategoryKind,
    OperationType,
    category_key,
    check_category_fits,
    check_transfer_accounts,
    require_category_editor,
    require_operation_editor,
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


@pytest.mark.parametrize(
    ("operation", "kind"),
    [(OperationType.EXPENSE, CategoryKind.EXPENSE), (OperationType.INCOME, CategoryKind.INCOME)],
)
def test_a_category_of_the_same_kind_fits(operation: OperationType, kind: CategoryKind) -> None:
    check_category_fits(operation, kind)


@pytest.mark.parametrize(
    ("operation", "kind"),
    [(OperationType.EXPENSE, CategoryKind.INCOME), (OperationType.INCOME, CategoryKind.EXPENSE)],
)
def test_a_category_of_the_other_kind_does_not_fit(
    operation: OperationType, kind: CategoryKind
) -> None:
    with pytest.raises(ValidationFailedError) as info:
        check_category_fits(operation, kind)

    assert info.value.code == "category_kind_mismatch"
    assert info.value.message == f"A {kind} category cannot be used for an {operation}"


def test_operation_types_have_stable_values() -> None:
    assert [t.value for t in OperationType] == ["income", "expense", "transfer"]


def test_a_transfer_takes_no_category() -> None:
    with pytest.raises(ValidationFailedError) as info:
        check_category_fits(OperationType.TRANSFER, CategoryKind.EXPENSE)

    assert info.value.code == "category_kind_mismatch"
    assert info.value.message == "A transfer has no category"


def test_a_transfer_between_two_accounts_is_valid() -> None:
    check_transfer_accounts(ANNA, IVAN)


def test_a_transfer_to_the_same_account_is_invalid() -> None:
    with pytest.raises(ValidationFailedError) as info:
        check_transfer_accounts(ANNA, ANNA)

    assert info.value.code == "transfer_same_account"
    assert info.value.message == "A transfer needs two different accounts"


@pytest.mark.parametrize(
    ("actor", "role", "author", "allowed"),
    [
        (ANNA, Role.MEMBER, ANNA, True),
        (IVAN, Role.MEMBER, ANNA, False),
        (IVAN, Role.OWNER, ANNA, True),
        (ANNA, Role.MEMBER, None, False),  # the author left the household
    ],
    ids=["author", "other-member", "owner", "author-gone"],
)
def test_who_may_change_an_operation(
    actor: uuid.UUID, role: Role, author: uuid.UUID | None, allowed: bool
) -> None:
    if allowed:
        require_operation_editor(actor_id=actor, role=role, author_id=author)
    else:
        with pytest.raises(PermissionDeniedError) as info:
            require_operation_editor(actor_id=actor, role=role, author_id=author)
        assert info.value.message == (
            "Only its author or the household owner can change this operation"
        )


def test_the_service_accepts_dates_of_this_century() -> None:
    assert (date(2000, 1, 1), date(2099, 12, 31)) == (EARLIEST_DATE, LATEST_DATE)
