"""Map every error to one JSON format: {"error": {"code", "message", "details"}}."""

from collections.abc import Mapping
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from family_pnl.core.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)

logger = structlog.get_logger(__name__)

# Most specific class first: a subclass inherits the status of its parent.
_DOMAIN_STATUS: tuple[tuple[type[DomainError], int], ...] = (
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
    (ValidationFailedError, status.HTTP_422_UNPROCESSABLE_CONTENT),
)

_HTTP_CODES = {
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_429_TOO_MANY_REQUESTS: "too_many_requests",
}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """Error format shared by every endpoint."""

    error: ErrorBody


def _error(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(
        jsonable_encoder(body), status_code=status_code, headers=dict(headers or {})
    )


def _status_for(error: DomainError) -> int:
    for cls, status_code in _DOMAIN_STATUS:
        if isinstance(error, cls):
            return status_code
    return status.HTTP_400_BAD_REQUEST


async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
    return _error(_status_for(exc), exc.code, exc.message)


async def _request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return _error(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "request_invalid", "Request is invalid", details
    )


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return _error(exc.status_code, code, str(exc.detail), headers=exc.headers)


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", path=request.url.path, exc_info=exc)
    return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    # The decorator form accepts handlers typed with their concrete exception class.
    app.exception_handler(DomainError)(_domain_error)
    app.exception_handler(RequestValidationError)(_request_invalid)
    app.exception_handler(StarletteHTTPException)(_http_error)
    app.exception_handler(Exception)(_unexpected)
