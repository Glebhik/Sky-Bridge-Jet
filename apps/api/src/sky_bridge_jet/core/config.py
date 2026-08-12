from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
DEFAULT_DEVELOPMENT_PASSWORD = "sky_bridge_jet_dev_only"
DEFAULT_DATABASE_NAME = "sky_bridge_jet"
DEFAULT_DATABASE_USER = "sky_bridge_jet"


def _repository_env_file(source_file: Path) -> Path:
    """Locate the repository .env for host tools, with an image-safe fallback."""
    for directory in (source_file.parent, *source_file.parents):
        if (directory / "pnpm-workspace.yaml").is_file():
            return directory / ".env"
    return Path.cwd() / ".env"


REPOSITORY_ENV_FILE = _repository_env_file(Path(__file__).resolve())

# Stripe live secret/restricted keys carry these prefixes; test keys use *_test_.
_STRIPE_LIVE_KEY_PREFIXES = ("sk_live_", "rk_live_")


def _is_stripe_live_key(secret_key: str) -> bool:
    return secret_key.startswith(_STRIPE_LIVE_KEY_PREFIXES)


class Settings(BaseSettings):
    """Typed runtime configuration with deliberately unsafe defaults rejected in production."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_environment: Environment = "development"
    database_name: str = DEFAULT_DATABASE_NAME
    database_user: str = DEFAULT_DATABASE_USER
    database_password: str = DEFAULT_DEVELOPMENT_PASSWORD
    database_host: str = "localhost"
    database_port: int = 5432
    database_url: str | None = None
    log_level: LogLevel = "INFO"

    # Stripe Connect is disabled by default: the application boots and tests run
    # without any Stripe configuration, using the provider-neutral fake adapter.
    # When enabled, Phase 7 permits TEST MODE ONLY and fails closed on live keys.
    stripe_enabled: bool = False
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_test_mode_required: bool = True
    stripe_account_country: str = "IE"

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> "Settings":
        if self.app_environment == "production":
            if self.database_url:
                return self
            insecure_values = {
                DEFAULT_DEVELOPMENT_PASSWORD,
                "change-me",
                "password",
            }
            if self.database_password.lower() in insecure_values:
                raise ValueError(
                    "DATABASE_PASSWORD must not use a development default in production"
                )
            if self.database_host in {"localhost", "127.0.0.1"}:
                raise ValueError("DATABASE_HOST must not target localhost in production")
            if self.database_name == DEFAULT_DATABASE_NAME:
                raise ValueError("DATABASE_NAME must be explicitly configured in production")
            if self.database_user == DEFAULT_DATABASE_USER:
                raise ValueError("DATABASE_USER must be explicitly configured in production")
        return self

    @model_validator(mode="after")
    def enforce_stripe_test_mode(self) -> "Settings":
        """Validate Stripe configuration and fail closed on live keys in test mode."""
        if not self.stripe_enabled:
            return self
        if not self.stripe_secret_key:
            raise ValueError("STRIPE_SECRET_KEY is required when STRIPE_ENABLED is set")
        if not self.stripe_webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is required when STRIPE_ENABLED is set")
        if self.stripe_test_mode_required and _is_stripe_live_key(self.stripe_secret_key):
            # Never echo the key itself.
            raise ValueError(
                "A live Stripe secret key is not permitted while STRIPE_TEST_MODE_REQUIRED is set"
            )
        return self

    @property
    def stripe_live_key_detected(self) -> bool:
        return self.stripe_secret_key is not None and _is_stripe_live_key(self.stripe_secret_key)

    @property
    def database_url_for_sync(self) -> URL | str:
        if self.database_url:
            return self.database_url
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.database_user,
            password=self.database_password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
