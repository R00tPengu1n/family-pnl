import json

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from family_pnl.api.main import create_app
from family_pnl.core.config import Settings
from family_pnl.core.logging import configure_logging


async def test_health_reports_ok_when_the_database_answers(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_reports_unavailable_database_with_503(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    # Port 1 on localhost refuses connections immediately.
    broken = settings.model_copy(
        update={"database_url": SecretStr("postgresql+asyncpg://u:p@127.0.0.1:1/none")}
    )
    configure_logging("INFO", json_output=True)
    app = create_app(broken)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get("/health")
    finally:
        await app.state.engine.dispose()
        await app.state.redis.aclose()
        await app.state.nbrb_http.aclose()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    warnings = [r for r in records if r["event"] == "database_unavailable"]
    assert len(warnings) == 1
    # Linux refuses a closed port at once; Windows retries until the 2 s timeout.
    assert warnings[0]["error"] in {"ConnectionRefusedError", "TimeoutError"}


async def test_openapi_schema_describes_health(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Family P&L API"
    assert "/health" in schema["paths"]


async def test_docs_page_is_served(client: AsyncClient) -> None:
    response = await client.get("/docs")

    assert response.status_code == 200
    assert "swagger" in response.text.lower()
