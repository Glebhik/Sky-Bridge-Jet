"""Provider-neutral, fail-closed privileged identity boundary (Phase 10.C)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    MissingRequiredClaimError,
    PyJWKClientError,
    PyJWKError,
    PyJWKSetError,
)
from jwt.exceptions import (
    InvalidTokenError as JwtInvalidTokenError,
)

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.modules.iam.domain import AuthenticationError


class PrivilegedIdentityError(AuthenticationError):
    """A normalized provider failure whose category is safe for audit, not the browser."""

    def __init__(self, classification: str) -> None:
        super().__init__("Staff authentication could not be completed")
        self.classification = classification


@dataclass(frozen=True)
class VerifiedIdentityAssertion:
    provider: str
    issuer: str
    subject: str
    auth_time: datetime
    mfa_verified_at: datetime
    provider_session_reference: str | None = None


class PrivilegedIdentityProvider(Protocol):
    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str: ...

    def exchange_and_verify(
        self, *, code: str, nonce: str, pkce_verifier: str
    ) -> VerifiedIdentityAssertion: ...


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class Auth0IdentityProvider:
    """Auth0 Authorization Code + PKCE adapter with signed ID-token verification."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        assert settings.auth0_issuer and settings.auth0_client_id and settings.auth0_callback_url
        self.issuer = settings.auth0_issuer.rstrip("/") + "/"
        self.algorithms = tuple(
            item.strip() for item in settings.auth0_allowed_algorithms.split(",") if item.strip()
        )
        if not self.algorithms or any(item != "RS256" for item in self.algorithms):
            raise ValueError("Only RS256 is approved for Auth0 privileged identity")
        self.jwks = PyJWKClient(f"{self.issuer}.well-known/jwks.json", cache_jwk_set=True)

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        query = {
            "response_type": "code",
            "client_id": self.settings.auth0_client_id,
            "redirect_uri": self.settings.auth0_callback_url,
            "scope": "openid profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if self.settings.auth0_audience:
            query["audience"] = self.settings.auth0_audience
        return f"{self.issuer}authorize?{urlencode(query)}"

    def exchange_and_verify(
        self, *, code: str, nonce: str, pkce_verifier: str
    ) -> VerifiedIdentityAssertion:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.settings.auth0_client_id,
            "code": code,
            "redirect_uri": self.settings.auth0_callback_url,
            "code_verifier": pkce_verifier,
        }
        if self.settings.auth0_client_secret:
            payload["client_secret"] = self.settings.auth0_client_secret
        request = Request(
            f"{self.issuer}oauth/token",
            data=urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed trusted issuer
                body = json.loads(response.read(128_000))
        except (URLError, TimeoutError, ValueError) as error:
            raise PrivilegedIdentityError("PROVIDER_UNAVAILABLE") from error
        token = body.get("id_token")
        if not isinstance(token, str):
            raise PrivilegedIdentityError("MISSING_ID_TOKEN")
        try:
            signing_key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.algorithms),
                audience=self.settings.auth0_client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            )
        except ExpiredSignatureError as error:
            raise PrivilegedIdentityError("TOKEN_EXPIRED") from error
        except InvalidIssuerError as error:
            raise PrivilegedIdentityError("INVALID_ISSUER") from error
        except InvalidAudienceError as error:
            raise PrivilegedIdentityError("AUDIENCE_MISMATCH") from error
        except InvalidSignatureError as error:
            raise PrivilegedIdentityError("INVALID_SIGNATURE") from error
        except MissingRequiredClaimError as error:
            classification = (
                "MISSING_SUBJECT" if error.claim == "sub" else "INVALID_SIGNED_ASSERTION"
            )
            raise PrivilegedIdentityError(classification) from error
        except (PyJWKClientError, PyJWKError, PyJWKSetError) as error:
            raise PrivilegedIdentityError("JWKS_UNAVAILABLE") from error
        except JwtInvalidTokenError as error:
            raise PrivilegedIdentityError("INVALID_SIGNED_ASSERTION") from error
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise PrivilegedIdentityError("NONCE_MISMATCH")
        methods = claims.get("amr")
        if (
            not isinstance(methods, list)
            or not all(isinstance(method, str) for method in methods)
            or "mfa" not in methods
        ):
            raise PrivilegedIdentityError("INSUFFICIENT_MFA")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise PrivilegedIdentityError("MISSING_SUBJECT")
        auth_time = claims.get("auth_time", claims.get("iat"))
        if not isinstance(auth_time, int | float):
            raise PrivilegedIdentityError("MISSING_AUTH_TIME")
        when = datetime.fromtimestamp(auth_time, UTC)
        return VerifiedIdentityAssertion(
            provider="auth0",
            issuer=self.issuer,
            subject=subject,
            auth_time=when,
            mfa_verified_at=when,
            provider_session_reference=cast(str | None, claims.get("sid")),
        )


class FakeIdentityProvider:
    """Server-owned deterministic test seam, impossible in staging/production."""

    def __init__(self, settings: Settings) -> None:
        if settings.app_environment not in {"development", "test"}:
            raise ValueError("FAKE privileged identity is forbidden outside development/test")
        if not settings.fake_privileged_identity_code:
            raise ValueError("FAKE_PRIVILEGED_IDENTITY_CODE is required for the fake adapter")
        self.code = settings.fake_privileged_identity_code

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        del nonce, code_challenge
        return f"/api/v1/auth/platform/callback?state={state}&code={self.code}"

    def exchange_and_verify(
        self, *, code: str, nonce: str, pkce_verifier: str
    ) -> VerifiedIdentityAssertion:
        del nonce, pkce_verifier
        if not secrets.compare_digest(code, self.code):
            raise PrivilegedIdentityError("INVALID_FAKE_ASSERTION")
        now = datetime.now(UTC)
        return VerifiedIdentityAssertion(
            provider="fake",
            issuer="urn:sky-bridge-jet:test-identity",
            subject="configured-test-platform-user",
            auth_time=now,
            mfa_verified_at=now,
        )


def build_privileged_identity_provider(settings: Settings) -> PrivilegedIdentityProvider:
    if settings.privileged_identity_provider == "auth0":
        return Auth0IdentityProvider(settings)
    if settings.privileged_identity_provider == "fake":
        return FakeIdentityProvider(settings)
    raise PrivilegedIdentityError("PRIVILEGED_IDENTITY_NOT_CONFIGURED")


def new_oidc_material() -> tuple[str, str, str, str]:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    return state, nonce, verifier, _b64url_sha256(verifier)
