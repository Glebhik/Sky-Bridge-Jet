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
