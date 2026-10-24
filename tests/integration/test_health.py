from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
