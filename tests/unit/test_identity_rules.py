import pytest

from family_pnl.core.errors import ValidationFailedError
from family_pnl.domain.identity import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    Role,
    check_password_policy,
    normalize_email,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Anna@Example.COM", "anna@example.com"),
        ("  ivan@example.com\t", "ivan@example.com"),
        ("already@lower.by", "already@lower.by"),
    ],
)
def test_email_is_trimmed_and_lowercased(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


def test_password_of_minimum_length_is_accepted() -> None:
    check_password_policy("a" * (MIN_PASSWORD_LENGTH - 1) + "b", email="anna@example.com")


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValidationFailedError, match=f"at least {MIN_PASSWORD_LENGTH}") as info:
        check_password_policy("short-pw1", email="anna@example.com")

    assert info.value.code == "weak_password"


def test_overlong_password_is_rejected() -> None:
    with pytest.raises(ValidationFailedError, match=f"at most {MAX_PASSWORD_LENGTH}"):
        check_password_policy("x" * (MAX_PASSWORD_LENGTH + 1), email="anna@example.com")


def test_password_equal_to_the_email_is_rejected() -> None:
    with pytest.raises(ValidationFailedError, match="email"):
        check_password_policy("Anna@Example.com", email="anna@example.com")


def test_blank_password_is_rejected() -> None:
    with pytest.raises(ValidationFailedError):
        check_password_policy(" " * MIN_PASSWORD_LENGTH, email="anna@example.com")


def test_roles_have_stable_values() -> None:
    assert {role.value for role in Role} == {"owner", "member"}
