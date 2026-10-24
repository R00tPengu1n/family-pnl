"""Every error leaves the API in one JSON format: {"error": {"code", "message", "details"}}."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from family_pnl.core.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)


class Payload(BaseModel):
    amount: int


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    errors: dict[str, DomainError] = {
        "not-found": NotFoundError("Account not found"),
        "conflict": ConflictError("Email already registered"),
        "denied": PermissionDeniedError("Only the owner can approve"),
        "invalid": ValidationFailedError("Category kind does not match"),
        "generic": DomainError("Something is wrong"),
        "unauthorized": AuthenticationError("Token is invalid or expired"),
    }

    @app.get("/_test/domain/{kind}")
    async def raise_domain_error(kind: str) -> None:
        raise errors[kind]

    @app.post("/_test/validate")
    async def validate(payload: Payload) -> Payload:
        return payload

    @app.get("/_test/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal detail")

    return app


@pytest.mark.parametrize(
    ("kind", "status", "code", "message"),
    [
        ("not-found", 404, "not_found", "Account not found"),
        ("conflict", 409, "conflict", "Email already registered"),
        ("denied", 403, "permission_denied", "Only the owner can approve"),
        ("invalid", 422, "validation_failed", "Category kind does not match"),
        ("generic", 400, "domain_error", "Something is wrong"),
        ("unauthorized", 401, "unauthorized", "Token is invalid or expired"),
    ],
)
async def test_domain_errors_map_to_status_and_common_format(
    client: AsyncClient, kind: str, status: int, code: str, message: str
) -> None:
    response = await client.get(f"/_test/domain/{kind}")

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": message, "details": None}}


async def test_request_validation_errors_use_common_format(client: AsyncClient) -> None:
    response = await client.post("/_test/validate", json={"amount": "many"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "request_invalid"
    assert error["details"][0]["loc"] == ["body", "amount"]


async def test_unknown_route_uses_common_format(client: AsyncClient) -> None:
    response = await client.get("/nowhere")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": None}
    }


async def test_unexpected_exception_hides_internal_details(client: AsyncClient) -> None:
    response = await client.get("/_test/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "details": None}
    }


async def test_authentication_errors_ask_for_a_bearer_token(client: AsyncClient) -> None:
    response = await client.get("/_test/domain/unauthorized")

    assert response.headers["www-authenticate"] == "Bearer"
