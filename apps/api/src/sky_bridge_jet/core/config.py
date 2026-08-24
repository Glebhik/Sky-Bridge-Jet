from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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

    # Phase 8 identity/session settings. Cookies are hardened by default; the
    # development environment may relax `Secure` (served over http) but production
    # must not. Session/token lifetimes are bounded.
    session_cookie_name: str = "sbj_session"
    csrf_cookie_name: str = "sbj_csrf"
    session_ttl_seconds: int = 60 * 60 * 12  # 12 hours
    email_verification_ttl_seconds: int = 60 * 60 * 24  # 24 hours
    password_reset_ttl_seconds: int = 60 * 60  # 1 hour
    invitation_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    # Cookie Secure flag. Defaults on; auto-relaxed for the development environment
    # unless explicitly overridden. Never silently weakened in production.
    session_cookie_secure: bool | None = None
    # Fixed-window auth rate limits (per identifier). A local, in-process floor;
    # production still fronts this with a reverse-proxy / WAF (documented).
    auth_rate_limit_max_attempts: int = 10
    auth_rate_limit_window_seconds: int = 60

    # Transactional auth email (Phase 9.2.B1) — DISABLED by default. The app boots and
    # all tests run with these blank, using the provider-neutral fake sender. When
    # enabled, a Resend API key is required (fail closed; the key is never echoed). The
    # sender address is server-controlled. WEB_PUBLIC_ORIGIN is the server-side base for
    # verification links; production requires an HTTPS origin when email is enabled.
    auth_email_enabled: bool = False
    resend_api_key: str | None = None
    auth_email_from: str = "Sky Bridge Jet <no-reply@skybridgejet.disgroup.ie>"
    web_public_origin: str = "http://localhost:3000"

    @property
    def cookie_secure_effective(self) -> bool:
        """Resolve the cookie Secure flag: explicit override, else on in production.

        Non-production environments (development/test) serve over plain http, so the
        Secure flag is off by default there; production always sets it (and the
        settings validator forbids disabling it in production).
        """
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_environment == "production"

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> "Settings":
        if self.app_environment == "production":
            # Cookie hardening applies regardless of how the database URL is supplied.
            if self.session_cookie_secure is False:
                raise ValueError("SESSION_COOKIE_SECURE must not be disabled in production")
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

    @model_validator(mode="after")
    def validate_auth_email(self) -> "Settings":
        """Normalize the public origin and fail closed on incomplete email config.

        ``WEB_PUBLIC_ORIGIN`` must be an absolute http(s) origin with no credentials,
        path, query, or fragment; it is normalized to ``scheme://host[:port]`` so a
        verification link can never be built from an unsafe base. When auth email is
        enabled a Resend API key is required (the error never contains the key), and
        production additionally requires an HTTPS origin.
        """
        parts = urlsplit(self.web_public_origin)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("WEB_PUBLIC_ORIGIN must be an absolute http(s) origin")
        if parts.username or parts.password:
            raise ValueError("WEB_PUBLIC_ORIGIN must not contain credentials")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("WEB_PUBLIC_ORIGIN must not contain a path, query, or fragment")
        # Normalize to the bare origin (drops a trailing slash and any component above).
        self.web_public_origin = f"{parts.scheme}://{parts.netloc}"

        if not self.auth_email_enabled:
            return self
        if not self.resend_api_key:
            # Never echo the key (there is none) and never hint at its value.
            raise ValueError("RESEND_API_KEY is required when AUTH_EMAIL_ENABLED is set")
        if self.app_environment == "production" and parts.scheme != "https":
            raise ValueError(
                "WEB_PUBLIC_ORIGIN must use https in production when AUTH_EMAIL_ENABLED is set"
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
