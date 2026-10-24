import json

import pytest
import structlog
from fastapi import FastAPI


async def test_startup_configures_json_logging(
    app: FastAPI, capsys: pytest.CaptureFixture[str]
) -> None:
    async with app.router.lifespan_context(app):
        structlog.get_logger("test").info("started")

    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "started"
