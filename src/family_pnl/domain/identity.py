"""Identity rules: roles, email normalisation and the password policy."""

from enum import StrEnum

from family_pnl.core.errors import ValidationFailedError

MIN_PASSWORD_LENGTH = 10
# argon2 accepts any length; the cap keeps hashing cost bounded for hostile input.
MAX_PASSWORD_LENGTH = 128


class Role(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class WeakPasswordError(ValidationFailedError):
    code = "weak_password"


def normalize_email(raw: str) -> str:
    """One canonical form, so `Anna@Example.com` and `anna@example.com` are one account."""
    return raw.strip().lower()


def check_password_policy(password: str, *, email: str) -> None:
    if not password.strip():
        raise WeakPasswordError("Password must not be blank")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Password must have at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Password must have at most {MAX_PASSWORD_LENGTH} characters")
    if normalize_email(password) == normalize_email(email):
        raise WeakPasswordError("Password must not be the same as the email")
