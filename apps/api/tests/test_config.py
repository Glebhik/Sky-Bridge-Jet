import pytest
from pydantic import ValidationError

from sky_bridge_jet.core.config import Settings


def test_production_rejects_development_database_password() -> None:
    with pytest.raises(ValidationError, match="DATABASE_PASSWORD"):
        Settings(app_environment="production")


def test_production_accepts_explicit_non_local_database_configuration() -> None:
    settings = Settings(
        app_environment="production",
        database_host="postgres.internal",
        database_password="a-strong-non-default-value",
    )

    assert settings.database_url_for_sync.startswith("postgresql+psycopg://")
