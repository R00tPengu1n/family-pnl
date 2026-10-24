import pytest
from pydantic import ValidationError

from family_pnl.core.config import Environment, Settings, get_settings

DATABASE_URL = "postgresql+asyncpg://app:s3cret@localhost:5432/family_pnl"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FAMILY_PNL_ENVIRONMENT",
        "FAMILY_PNL_LOG_LEVEL",
        "FAMILY_PNL_LOG_JSON",
        "FAMILY_PNL_DEFAULT_TIMEZONE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAMILY_PNL_DATABASE_URL", DATABASE_URL)


def test_defaults_are_safe_for_local_development() -> None:
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


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAMILY_PNL_DATABASE_URL")

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_database_url_must_use_the_asyncpg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_DATABASE_URL", "postgresql://app:pw@localhost/family_pnl")

    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(_env_file=None)


def test_database_password_is_hidden_in_repr_but_available_to_code() -> None:
    settings = Settings(_env_file=None)

    assert "s3cret" not in repr(settings)
    assert settings.database_url.get_secret_value() == DATABASE_URL


def test_get_settings_reads_the_environment_once() -> None:
    get_settings.cache_clear()
    try:
        first = get_settings()

        assert first is get_settings()
        assert first.database_url.get_secret_value() == DATABASE_URL
    finally:
        get_settings.cache_clear()
