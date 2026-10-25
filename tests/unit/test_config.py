from datetime import timedelta

import pytest
from pydantic import ValidationError

from family_pnl.core.config import Environment, Settings, get_settings

DATABASE_URL = "postgresql+asyncpg://app:s3cret@localhost:5432/family_pnl"
JWT_SECRET = "x" * 32


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FAMILY_PNL_ENVIRONMENT",
        "FAMILY_PNL_LOG_LEVEL",
        "FAMILY_PNL_LOG_JSON",
        "FAMILY_PNL_DEFAULT_TIMEZONE",
        "FAMILY_PNL_BOT_API_SECRET",
        "FAMILY_PNL_TELEGRAM_BOT_TOKEN",
        "FAMILY_PNL_BUDGET_WINDOW_START_DAY",
        "FAMILY_PNL_BUDGET_WINDOW_END_DAY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAMILY_PNL_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("FAMILY_PNL_JWT_SECRET", JWT_SECRET)


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


def test_token_lifetimes_default_to_the_spec() -> None:
    settings = Settings(_env_file=None)

    assert settings.access_token_ttl == timedelta(minutes=15)
    assert settings.refresh_token_ttl == timedelta(days=30)


def test_jwt_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAMILY_PNL_JWT_SECRET")

    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None)


def test_short_jwt_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # HS256 needs a key at least as long as its 256-bit output.
    monkeypatch.setenv("FAMILY_PNL_JWT_SECRET", "x" * 31)

    with pytest.raises(ValidationError, match="32"):
        Settings(_env_file=None)


def test_login_rate_limit_defaults_to_5_failures_per_15_minutes() -> None:
    settings = Settings(_env_file=None)

    assert settings.login_max_failures == 5
    assert settings.login_failure_window == timedelta(minutes=15)


def test_redis_url_defaults_to_the_local_dev_instance() -> None:
    settings = Settings(_env_file=None)

    assert settings.redis_url.get_secret_value() == "redis://127.0.0.1:6379/0"


def test_redis_url_must_use_a_redis_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_REDIS_URL", "http://127.0.0.1:6379/0")

    with pytest.raises(ValidationError, match="redis://"):
        Settings(_env_file=None)


def test_bot_api_is_disabled_without_a_secret() -> None:
    assert Settings(_env_file=None).bot_api_secret is None


def test_short_bot_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_BOT_API_SECRET", "x" * 31)

    with pytest.raises(ValidationError, match="32"):
        Settings(_env_file=None)


def test_bot_secret_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_BOT_API_SECRET", "b0t-" * 10)

    settings = Settings(_env_file=None)

    assert "b0t-" not in repr(settings)
    assert settings.bot_api_secret is not None


@pytest.mark.parametrize("value", [None, ""], ids=["absent", "empty"])
def test_notifications_wait_without_a_telegram_token(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is not None:
        monkeypatch.setenv("FAMILY_PNL_TELEGRAM_BOT_TOKEN", value)

    assert Settings(_env_file=None).telegram_bot_token is None


def test_the_telegram_token_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_TELEGRAM_BOT_TOKEN", "123456:telegram-token")

    settings = Settings(_env_file=None)

    assert "telegram-token" not in repr(settings)
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == "123456:telegram-token"
    assert settings.telegram_api_url == "https://api.telegram.org"


def test_validation_errors_do_not_show_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_BOT_API_SECRET", "short-but-secret")

    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None)

    assert "short-but-secret" not in str(raised.value)


def test_a_budget_window_that_ends_before_it_starts_is_rejected_at_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAMILY_PNL_BUDGET_WINDOW_START_DAY", "25")
    monkeypatch.setenv("FAMILY_PNL_BUDGET_WINDOW_END_DAY", "10")

    with pytest.raises(ValidationError, match="must not end before it starts"):
        Settings(_env_file=None)


def test_a_one_day_budget_window_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_PNL_BUDGET_WINDOW_START_DAY", "25")
    monkeypatch.setenv("FAMILY_PNL_BUDGET_WINDOW_END_DAY", "25")

    settings = Settings(_env_file=None)

    assert (settings.budget_window_start_day, settings.budget_window_end_day) == (25, 25)
