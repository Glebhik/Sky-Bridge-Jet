from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
DEFAULT_DEVELOPMENT_PASSWORD = "sky_bridge_jet_dev_only"


class Settings(BaseSettings):
    """Typed runtime configuration with deliberately unsafe defaults rejected in production."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_environment: Environment = "development"
    database_name: str = "sky_bridge_jet"
    database_user: str = "sky_bridge_jet"
    database_password: str = DEFAULT_DEVELOPMENT_PASSWORD
    database_host: str = "localhost"
    database_port: int = 5432
    database_url: str | None = None
    log_level: str = "INFO"

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> "Settings":
        if self.app_environment == "production":
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
        return self

    @property
    def database_url_for_sync(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
