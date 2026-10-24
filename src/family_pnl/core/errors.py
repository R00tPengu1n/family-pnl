"""Domain error hierarchy.

Services raise these; the API maps each kind to an HTTP status and one JSON error format.
`code` is a stable machine-readable identifier; subclasses may refine it.
"""

from typing import ClassVar


class DomainError(Exception):
    code: ClassVar[str] = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """The object does not exist or belongs to another household."""

    code = "not_found"


class ConflictError(DomainError):
    code = "conflict"


class AuthenticationError(DomainError):
    """Missing, invalid or expired credentials."""

    code = "unauthorized"


class PermissionDeniedError(DomainError):
    code = "permission_denied"


class ValidationFailedError(DomainError):
    """Input is well-formed but violates a business rule."""

    code = "validation_failed"


class UnavailableError(DomainError):
    """A dependency the request needs is down and there is no usable fallback."""

    code = "unavailable"


class RateLimitedError(DomainError):
    """Too many attempts; the client may retry after `retry_after` seconds."""

    code = "too_many_attempts"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after
