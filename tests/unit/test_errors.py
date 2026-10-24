from family_pnl.core.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)


def test_domain_error_carries_a_stable_code_and_message() -> None:
    error = NotFoundError("Account not found")

    assert isinstance(error, DomainError)
    assert error.code == "not_found"
    assert error.message == "Account not found"
    assert str(error) == "Account not found"


def test_each_error_kind_has_its_own_code() -> None:
    codes = {
        cls("x").code
        for cls in (NotFoundError, ConflictError, PermissionDeniedError, ValidationFailedError)
    }

    assert codes == {"not_found", "conflict", "permission_denied", "validation_failed"}


def test_subclass_can_override_the_code() -> None:
    class InviteExpiredError(ConflictError):
        code = "invite_expired"

    assert InviteExpiredError("Invite has expired").code == "invite_expired"
