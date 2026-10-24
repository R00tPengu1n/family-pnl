import json
import logging

import pytest
import structlog

from family_pnl.core.logging import configure_logging


def last_json_line(out: str) -> dict[str, object]:
    record: dict[str, object] = json.loads(out.strip().splitlines()[-1])
    return record


def test_json_logging_writes_one_json_object_per_event(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)

    structlog.get_logger("test").info("rate_refreshed", currency="USD")

    record = last_json_line(capsys.readouterr().out)
    assert record["event"] == "rate_refreshed"
    assert record["currency"] == "USD"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_events_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="WARNING", json_output=True)

    structlog.get_logger("test").info("hidden")
    structlog.get_logger("test").warning("shown")

    out = capsys.readouterr().out
    assert "hidden" not in out
    assert "shown" in out


def test_standard_library_logs_are_rendered_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)

    logging.getLogger("some.library").warning("connection %s lost", "db")

    record = last_json_line(capsys.readouterr().out)
    assert record["event"] == "connection db lost"
    assert record["level"] == "warning"
    assert record["logger"] == "some.library"


def test_uvicorn_loggers_are_taken_over(capsys: pytest.CaptureFixture[str]) -> None:
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.addHandler(logging.StreamHandler())
    uvicorn_error.propagate = False

    configure_logging(level="INFO", json_output=True)
    uvicorn_error.info("Application startup complete.")

    assert uvicorn_error.handlers == []
    record = last_json_line(capsys.readouterr().out)
    assert record["event"] == "Application startup complete."
