import json

import pytest
import structlog

from family_pnl.core.logging import configure_logging


def test_json_logging_writes_one_json_object_per_event(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_output=True)

    structlog.get_logger("test").info("rate_refreshed", currency="USD")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
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
