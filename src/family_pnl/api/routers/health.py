from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

from family_pnl.api.deps import get_engine
from family_pnl.core.db import ping

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok", "database": "ok"}]})

    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


@router.get(
    "/health",
    summary="Health check including the database",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def get_health(
    response: Response, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> HealthResponse:
    if await ping(engine):
        return HealthResponse(status="ok", database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable", database="unavailable")
