import pytest

from family_pnl.core.errors import ValidationFailedError
from family_pnl.domain.identity import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    Role,
    WeakPasswordError,
    check_password_policy,
    normalize_email,
)

EMAIL = "anna@example.com"


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


def test_length_limits_are_the_documented_ones() -> None:
    # Literal numbers on purpose: the limits are part of the API contract.
    assert (MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH) == (10, 128)


@pytest.mark.parametrize("length", [10, 11, 127, 128])
def test_passwords_within_the_limits_are_accepted(length: int) -> None:
    check_password_policy("p" * (length - 1) + "!", email=EMAIL)


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("p" * 9, "Password must have at least 10 characters"),
        ("p" * 129, "Password must have at most 128 characters"),
        (" " * 12, "Password must not be blank"),
        ("Anna@Example.com", "Password must not be the same as the email"),
    ],
    ids=["too-short", "too-long", "blank", "same-as-email"],
)
def test_weak_passwords_are_rejected_with_a_clear_message(password: str, message: str) -> None:
    with pytest.raises(WeakPasswordError) as info:
        check_password_policy(password, email=EMAIL)

    assert info.value.message == message
    assert info.value.code == "weak_password"
    assert isinstance(info.value, ValidationFailedError)


def test_password_equal_to_the_email_is_compared_after_normalisation() -> None:
    with pytest.raises(WeakPasswordError):
        check_password_policy("  ANNA@example.com ", email="Anna@Example.com")


def test_password_containing_the_email_is_allowed() -> None:
    check_password_policy("anna@example.com and more", email=EMAIL)


def test_roles_have_stable_values() -> None:
    assert [role.value for role in Role] == ["owner", "member"]
