import pytest
from pydantic import ValidationError

from family_pnl.core.config import Environment, Settings


def test_defaults_are_safe_for_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FAMILY_PNL_ENVIRONMENT", "FAMILY_PNL_LOG_LEVEL", "FAMILY_PNL_LOG_JSON"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.environment is Environment.LOCAL
    assert settings.log_level == "INFO"
    assert settings.log_json is False
    assert settings.default_timezone == "Europe/Minsk"


def test_settings_are_read_from_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_ENVIRONMENT", "production")
    monkeypatch.setenv("FAMILY_PNL_LOG_LEVEL", "warning")
    monkeypatch.setenv("FAMILY_PNL_LOG_JSON", "true")

    settings = Settings(_env_file=None)

    assert settings.environment is Environment.PRODUCTION
    assert settings.log_level == "WARNING"
    assert settings.log_json is True


def test_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unknown_time_zone_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_DEFAULT_TIMEZONE", "Mars/Olympus")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
