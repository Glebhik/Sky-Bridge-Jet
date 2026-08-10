import pytest
from pydantic import ValidationError
from sqlalchemy import make_url

from sky_bridge_jet.core.config import (
    DEFAULT_DATABASE_NAME,
    DEFAULT_DATABASE_USER,
    Settings,
)

SETTINGS_ENVIRONMENT_VARIABLES = (
    "APP_ENVIRONMENT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_URL",
    "LOG_LEVEL",
)


def settings_without_environment(monkeypatch: pytest.MonkeyPatch, **values: object) -> Settings:
    for variable in SETTINGS_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    return Settings(_env_file=None, **values)


def test_development_uses_documented_component_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_without_environment(monkeypatch)

    assert settings.app_environment == "development"
    assert settings.database_host == "localhost"
    assert settings.database_url is None


def test_production_rejects_missing_component_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="DATABASE_PASSWORD"):
        settings_without_environment(monkeypatch, app_environment="production")


def test_production_accepts_explicit_database_url_without_component_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_without_environment(
        monkeypatch,
        app_environment="production",
        database_url="postgresql+psycopg://api:strong-password@postgres.internal:5432/app",
    )

    assert settings.database_url_for_sync == (
        "postgresql+psycopg://api:strong-password@postgres.internal:5432/app"
    )


def test_production_accepts_explicit_non_default_component_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_without_environment(
        monkeypatch,
        app_environment="production",
        database_host="postgres.internal",
        database_password="a-strong-non-default-value",
        database_name="production_app",
        database_user="production_api",
    )

    assert str(settings.database_url_for_sync).startswith("postgresql+psycopg://")


def test_production_rejects_default_database_identity_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="DATABASE_NAME"):
        settings_without_environment(
            monkeypatch,
            app_environment="production",
            database_host="postgres.internal",
            database_password="a-strong-non-default-value",
            database_name=DEFAULT_DATABASE_NAME,
            database_user=DEFAULT_DATABASE_USER,
        )


def test_component_database_url_encodes_reserved_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_without_environment(
        monkeypatch,
        database_user="user@name",
        database_password="p@ss:/?word",
    )

    url = make_url(settings.database_url_for_sync)

    assert url.username == "user@name"
    assert url.password == "p@ss:/?word"
    rendered_url = settings.database_url_for_sync.render_as_string(hide_password=False)
    assert make_url(rendered_url).password == "p@ss:/?word"
