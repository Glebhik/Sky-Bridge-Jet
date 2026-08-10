import pytest
from pydantic import ValidationError
from sqlalchemy import make_url

from sky_bridge_jet.core.config import (
    DEFAULT_DATABASE_NAME,
    DEFAULT_DATABASE_USER,
    Settings,
)


def test_development_uses_documented_component_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_environment == "development"
    assert settings.database_host == "localhost"
    assert settings.database_url is None


def test_production_rejects_missing_component_configuration() -> None:
    with pytest.raises(ValidationError, match="DATABASE_PASSWORD"):
        Settings(app_environment="production", _env_file=None)


def test_production_accepts_explicit_database_url_without_component_values() -> None:
    settings = Settings(
        app_environment="production",
        database_url="postgresql+psycopg://api:strong-password@postgres.internal:5432/app",
        _env_file=None,
    )

    assert settings.database_url_for_sync == (
        "postgresql+psycopg://api:strong-password@postgres.internal:5432/app"
    )


def test_production_accepts_explicit_non_default_component_configuration() -> None:
    settings = Settings(
        app_environment="production",
        database_host="postgres.internal",
        database_password="a-strong-non-default-value",
        database_name="production_app",
        database_user="production_api",
        _env_file=None,
    )

    assert str(settings.database_url_for_sync).startswith("postgresql+psycopg://")


def test_production_rejects_default_database_identity_values() -> None:
    with pytest.raises(ValidationError, match="DATABASE_NAME"):
        Settings(
            app_environment="production",
            database_host="postgres.internal",
            database_password="a-strong-non-default-value",
            database_name=DEFAULT_DATABASE_NAME,
            database_user=DEFAULT_DATABASE_USER,
            _env_file=None,
        )


def test_component_database_url_encodes_reserved_characters() -> None:
    settings = Settings(
        database_user="user@name",
        database_password="p@ss:/?word",
        _env_file=None,
    )

    url = make_url(settings.database_url_for_sync)

    assert url.username == "user@name"
    assert url.password == "p@ss:/?word"
    rendered_url = settings.database_url_for_sync.render_as_string(hide_password=False)
    assert make_url(rendered_url).password == "p@ss:/?word"
