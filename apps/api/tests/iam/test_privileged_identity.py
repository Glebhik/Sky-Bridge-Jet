from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.error import URLError
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from iam_support import platform_role_client, product_owner_client, product_owner_client_with_user
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.main import app
from sky_bridge_jet.modules.iam import privileged_identity as privileged_identity_module
from sky_bridge_jet.modules.iam.domain import (
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import (
    ExternalIdentityLink,
    Organization,
    OrganizationMembership,
    PrivilegedAuthTransaction,
    User,
    UserSession,
)
from sky_bridge_jet.modules.iam.privileged_identity import (
    Auth0IdentityProvider,
    FakeIdentityProvider,
    PrivilegedIdentityError,
    VerifiedIdentityAssertion,
)
from sky_bridge_jet.modules.iam.privileged_services import PrivilegedIdentityService
from sky_bridge_jet.modules.iam.security import hash_token
from sky_bridge_jet.modules.route_policy import enumerate_app_routes

_ISSUER = "https://tenant.eu.auth0.com/"
_AUDIENCE = "staff-client"
_NONCE = "server-owned-nonce"


class _TokenResponse:
    def __init__(self, token: str) -> None:
        self.token = token

    def __enter__(self) -> _TokenResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps({"id_token": self.token}).encode()


class _SigningKeyClient:
    def __init__(self, key: rsa.RSAPublicKey | None = None, error: Exception | None = None) -> None:
        self.key = key
        self.error = error
        self.calls = 0

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.key is not None
        return SimpleNamespace(key=self.key)


def _auth0_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        privileged_identity_provider="auth0",
        auth0_issuer=_ISSUER,
        auth0_client_id=_AUDIENCE,
        auth0_callback_url="http://localhost:8000/api/v1/auth/platform/callback",
        auth0_environment_id="test",
    )


@pytest.fixture(scope="module")
def rsa_keys() -> tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048), rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": "auth0|staff-1",
        "exp": now + 300,
        "iat": now,
        "auth_time": now,
        "nonce": _NONCE,
        "amr": ["mfa"],
    }
    claims.update(overrides)
    for key in tuple(claims):
        if claims[key] is _MISSING:
            del claims[key]
    return claims


_MISSING = object()


def _signed_token(
    key: rsa.RSAPrivateKey,
    *,
    claims: dict[str, Any] | None = None,
    algorithm: str = "RS256",
    kid: str = "key-a",
) -> str:
    return jwt.encode(claims or _claims(), key, algorithm=algorithm, headers={"kid": kid})


def _jwk(key: rsa.RSAPublicKey, kid: str) -> dict[str, Any]:
    value = RSAAlgorithm.to_jwk(key, as_dict=True)
    assert isinstance(value, dict)
    return {**value, "kid": kid, "use": "sig", "alg": "RS256"}


def _verify(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    verification_key: rsa.RSAPublicKey,
) -> Any:
    provider = Auth0IdentityProvider(_auth0_settings())
    provider.jwks = _SigningKeyClient(verification_key)  # type: ignore[assignment]
    monkeypatch.setattr(
        privileged_identity_module, "urlopen", lambda *_args, **_kwargs: _TokenResponse(token)
    )
    return provider.exchange_and_verify(code="opaque-code", nonce=_NONCE, pkce_verifier="verifier")


def _expect_failure(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    verification_key: rsa.RSAPublicKey,
    classification: str,
) -> None:
    with pytest.raises(PrivilegedIdentityError) as captured:
        _verify(monkeypatch, token, verification_key)
    assert captured.value.classification == classification
    assert token not in str(captured.value)


def test_real_auth0_adapter_accepts_canonical_rs256_mfa_assertion(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]
) -> None:
    key, _ = rsa_keys
    assertion = _verify(monkeypatch, _signed_token(key), key.public_key())
    assert assertion.issuer == _ISSUER
    assert assertion.subject == "auth0|staff-1"
    assert assertion.provider == "auth0"
    assert assertion.mfa_verified_at == assertion.auth_time


def test_real_auth0_adapter_rejects_invalid_signature_and_wrong_key(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]
) -> None:
    key_a, key_b = rsa_keys
    _expect_failure(
        monkeypatch, _signed_token(key_b, kid="key-a"), key_a.public_key(), "INVALID_SIGNATURE"
    )


def test_real_auth0_adapter_rejects_none_and_wrong_algorithm(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]
) -> None:
    key, _ = rsa_keys
    unsigned = jwt.encode(_claims(), key="", algorithm="none", headers={"kid": "key-a"})
    _expect_failure(monkeypatch, unsigned, key.public_key(), "INVALID_SIGNED_ASSERTION")
    hs256 = jwt.encode(
        _claims(), key="test-only-hmac-key", algorithm="HS256", headers={"kid": "key-a"}
    )
    _expect_failure(monkeypatch, hs256, key.public_key(), "INVALID_SIGNED_ASSERTION")


@pytest.mark.parametrize(
    ("overrides", "classification"),
    [
        ({"iss": "https://other.eu.auth0.com/"}, "INVALID_ISSUER"),
        ({"iss": "https://tenant.eu.auth0.com.evil.example/"}, "INVALID_ISSUER"),
        ({"iss": "http://tenant.eu.auth0.com/"}, "INVALID_ISSUER"),
        ({"aud": "other-client"}, "AUDIENCE_MISMATCH"),
        ({"aud": _MISSING}, "INVALID_SIGNED_ASSERTION"),
        ({"nonce": "wrong"}, "NONCE_MISMATCH"),
        ({"nonce": _MISSING}, "INVALID_SIGNED_ASSERTION"),
        ({"sub": _MISSING}, "MISSING_SUBJECT"),
        ({"sub": ""}, "MISSING_SUBJECT"),
    ],
)
def test_real_auth0_adapter_rejects_identity_claim_attacks(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
    overrides: dict[str, Any],
    classification: str,
) -> None:
    key, _ = rsa_keys
    _expect_failure(
        monkeypatch,
        _signed_token(key, claims=_claims(**overrides)),
        key.public_key(),
        classification,
    )


@pytest.mark.parametrize(
    "amr",
    [
        _MISSING,
        [],
        ["pwd"],
        ["password"],
        "mfa",
        None,
        1,
        {"mfa": True},
        ["not-mfa"],
        ["mfa_fake"],
        ["pwd", "otp"],
        ["mfa", 1],
    ],
)
def test_real_auth0_adapter_rejects_missing_non_mfa_and_malformed_amr(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
    amr: Any,
) -> None:
    key, _ = rsa_keys
    _expect_failure(
        monkeypatch,
        _signed_token(key, claims=_claims(amr=amr)),
        key.public_key(),
        "INSUFFICIENT_MFA",
    )


@pytest.mark.parametrize(
    ("overrides", "classification"),
    [
        ({"exp": 1}, "TOKEN_EXPIRED"),
        ({"exp": "not-a-time"}, "INVALID_SIGNED_ASSERTION"),
        ({"iat": "not-a-time"}, "INVALID_SIGNED_ASSERTION"),
        ({"auth_time": "not-a-time"}, "MISSING_AUTH_TIME"),
        ({"nbf": int(datetime.now(UTC).timestamp()) + 3600}, "INVALID_SIGNED_ASSERTION"),
    ],
)
def test_real_auth0_adapter_rejects_expired_and_malformed_time_claims(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
    overrides: dict[str, Any],
    classification: str,
) -> None:
    key, _ = rsa_keys
    _expect_failure(
        monkeypatch,
        _signed_token(key, claims=_claims(**overrides)),
        key.public_key(),
        classification,
    )


def test_real_auth0_adapter_normalizes_jwks_failures_without_token_leak(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]
) -> None:
    key, _ = rsa_keys
    token = _signed_token(key, kid="unknown")
    provider = Auth0IdentityProvider(_auth0_settings())
    provider.jwks = _SigningKeyClient(error=PyJWKClientError("unable to find signing key"))  # type: ignore[assignment]
    monkeypatch.setattr(
        privileged_identity_module, "urlopen", lambda *_args, **_kwargs: _TokenResponse(token)
    )
    with pytest.raises(PrivilegedIdentityError) as captured:
        provider.exchange_and_verify(code="opaque", nonce=_NONCE, pkce_verifier="verifier")
    assert captured.value.classification == "JWKS_UNAVAILABLE"
    assert token not in str(captured.value)


@pytest.mark.parametrize("provider_error", [URLError("offline"), TimeoutError("timeout")])
def test_real_auth0_adapter_normalizes_token_endpoint_network_failure(
    monkeypatch: pytest.MonkeyPatch, provider_error: Exception
) -> None:
    provider = Auth0IdentityProvider(_auth0_settings())

    def fail(*_args: object, **_kwargs: object) -> _TokenResponse:
        raise provider_error

    monkeypatch.setattr(privileged_identity_module, "urlopen", fail)
    with pytest.raises(PrivilegedIdentityError) as captured:
        provider.exchange_and_verify(
            code="secret-authorization-code", nonce=_NONCE, pkce_verifier="secret-verifier"
        )
    assert captured.value.classification == "PROVIDER_UNAVAILABLE"
    assert "secret-authorization-code" not in str(captured.value)
    assert "secret-verifier" not in str(captured.value)


def test_real_auth0_adapter_refreshes_unknown_kid_and_accepts_rotated_key(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]
) -> None:
    old_key, new_key = rsa_keys
    token = _signed_token(new_key, kid="key-new")
    provider = Auth0IdentityProvider(_auth0_settings())
    responses = iter(
        [
            {"keys": [_jwk(old_key.public_key(), "key-old")]},
            {"keys": [_jwk(new_key.public_key(), "key-new")]},
        ]
    )
    calls = 0

    def fetch_data() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(provider.jwks, "fetch_data", fetch_data)
    monkeypatch.setattr(
        privileged_identity_module, "urlopen", lambda *_args, **_kwargs: _TokenResponse(token)
    )
    assertion = provider.exchange_and_verify(code="opaque", nonce=_NONCE, pkce_verifier="verifier")
    assert assertion.subject == "auth0|staff-1"
    assert calls == 2


def test_real_auth0_adapter_rejects_permanently_unknown_kid(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey]
) -> None:
    old_key, new_key = rsa_keys
    token = _signed_token(new_key, kid="key-new")
    provider = Auth0IdentityProvider(_auth0_settings())
    calls = 0

    def fetch_data() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"keys": [_jwk(old_key.public_key(), "key-old")]}

    monkeypatch.setattr(provider.jwks, "fetch_data", fetch_data)
    monkeypatch.setattr(
        privileged_identity_module, "urlopen", lambda *_args, **_kwargs: _TokenResponse(token)
    )
    with pytest.raises(PrivilegedIdentityError) as captured:
        provider.exchange_and_verify(code="opaque", nonce=_NONCE, pkce_verifier="verifier")
    assert captured.value.classification == "JWKS_UNAVAILABLE"
    assert calls == 2


@pytest.mark.parametrize(
    "jwks",
    [{"keys": "not-a-list"}, {"keys": [{}]}, {"keys": [{"kty": "RSA", "kid": "key-a"}]}],
)
def test_real_auth0_adapter_normalizes_malformed_jwks(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPrivateKey],
    jwks: dict[str, Any],
) -> None:
    key, _ = rsa_keys
    token = _signed_token(key)
    provider = Auth0IdentityProvider(_auth0_settings())
    monkeypatch.setattr(provider.jwks, "fetch_data", lambda: jwks)
    monkeypatch.setattr(
        privileged_identity_module, "urlopen", lambda *_args, **_kwargs: _TokenResponse(token)
    )
    with pytest.raises(PrivilegedIdentityError) as captured:
        provider.exchange_and_verify(code="opaque", nonce=_NONCE, pkce_verifier="verifier")
    assert captured.value.classification == "JWKS_UNAVAILABLE"
    assert token not in str(captured.value)


def test_fake_provider_is_server_configured_and_mfa_assured() -> None:
    settings = Settings(
        app_environment="test",
        privileged_identity_provider="fake",
        fake_privileged_identity_code="server-owned-test-code",
    )
    provider = FakeIdentityProvider(settings)
    assertion = provider.exchange_and_verify(
        code="server-owned-test-code", nonce="opaque", pkce_verifier="opaque"
    )
    assert assertion.provider == "fake"
    assert assertion.issuer == "urn:sky-bridge-jet:test-identity"
    with pytest.raises(PrivilegedIdentityError):
        provider.exchange_and_verify(code="browser-input", nonce="x", pkce_verifier="x")


def test_fake_provider_is_impossible_in_staging() -> None:
    with pytest.raises(ValueError, match="Auth0 privileged identity"):
        Settings(
            app_environment="staging",
            database_url="postgresql+psycopg://u:p@db/x",
            privileged_identity_provider="fake",
            fake_privileged_identity_code="never",
        )


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_local_password_platform_session_is_denied_and_expiry_fails_closed() -> None:
    client = product_owner_client()
    assert client.get("/api/v1/platform/pilot/state").status_code == 200
    with SessionLocal() as session, session.begin():
        record = session.scalars(
            select(UserSession).order_by(UserSession.created_at.desc())
        ).first()
        assert record is not None
        record.identity_provider = None
        record.mfa_verified_at = None
        record.assurance_expires_at = None
    assert client.get("/api/v1/platform/pilot/state").status_code == 401


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_expired_assurance_and_identity_link_uniqueness() -> None:
    client = product_owner_client()
    with SessionLocal() as session, session.begin():
        record = session.scalars(
            select(UserSession).order_by(UserSession.created_at.desc())
        ).first()
        assert record is not None
        record.assurance_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        links = list(
            session.scalars(
                select(ExternalIdentityLink).where(ExternalIdentityLink.user_id == record.user_id)
            )
        )
        assert len(links) == 1
    assert client.get("/api/v1/platform/pilot/state").status_code == 401


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_operational_diagnostics_are_bounded_and_admin_only() -> None:
    client = product_owner_client()
    response = client.get("/api/v1/platform/operations/diagnostics")
    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "status",
        "environment_safe",
        "payment_unknown",
        "payment_unknown_oldest_seconds",
        "outbox_pending",
        "outbox_oldest_due_seconds",
        "outbox_retryable",
        "outbox_permanent",
        "outbox_bounced",
        "outbox_complained",
        "outbox_suppressed",
        "outbox_systemic_provider_failures",
        "outbox_expired_claims",
        "admissions_pending",
        "admissions_oldest_seconds",
        "evidence_pending",
        "evidence_oldest_seconds",
        "pilot_mode",
        "payment_initiation_enabled",
        "active_participants",
    }


class _VerifiedProvider:
    def __init__(self, *, issuer: str = _ISSUER, subject: str = "auth0|callback-user") -> None:
        self.issuer = issuer
        self.subject = subject

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        del nonce, code_challenge
        return f"https://tenant.eu.auth0.com/authorize?state={state}"

    def exchange_and_verify(
        self, *, code: str, nonce: str, pkce_verifier: str
    ) -> VerifiedIdentityAssertion:
        assert code == "valid-code"
        assert nonce and pkce_verifier
        now = datetime.now(UTC)
        return VerifiedIdentityAssertion(
            provider="auth0",
            issuer=self.issuer,
            subject=self.subject,
            auth_time=now,
            mfa_verified_at=now,
        )


class _RejectingProvider(_VerifiedProvider):
    def __init__(self, classification: str) -> None:
        super().__init__()
        self.classification = classification

    def exchange_and_verify(
        self, *, code: str, nonce: str, pkce_verifier: str
    ) -> VerifiedIdentityAssertion:
        del code, nonce, pkce_verifier
        raise PrivilegedIdentityError(self.classification)


def _create_linked_staff(
    *,
    subject: str = "auth0|callback-user",
    status: UserStatus = UserStatus.ACTIVE,
    membership_status: MembershipStatus | None = MembershipStatus.ACTIVE,
    organization_type: OrganizationType = OrganizationType.PLATFORM,
) -> UUID:
    email = f"staff+{uuid4().hex}@example.test"
    with SessionLocal() as session, session.begin():
        user = User(
            email=email,
            normalized_email=email,
            password_hash=None,
            status=status,
        )
        session.add(user)
        session.flush()
        org = Organization(organization_type=organization_type, display_name="Test organization")
        session.add(org)
        session.flush()
        if membership_status is not None:
            session.add(
                OrganizationMembership(
                    user_id=user.id,
                    organization_id=org.id,
                    role=(
                        OrganizationRole.PRODUCT_OWNER
                        if organization_type is OrganizationType.PLATFORM
                        else OrganizationRole.CUSTOMER_OWNER
                    ),
                    status=membership_status,
                )
            )
        session.add(
            ExternalIdentityLink(
                user_id=user.id,
                provider="auth0",
                issuer=_ISSUER,
                subject=subject,
            )
        )
        return user.id


def _callback_settings() -> Settings:
    return Settings(_env_file=None, app_environment="test")


def _session_count() -> int:
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(UserSession)) or 0


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_callback_happy_path_consumes_state_and_replay_creates_no_second_session() -> None:
    subject = f"auth0|{uuid4()}"
    user_id = _create_linked_staff(subject=subject)
    provider = _VerifiedProvider(subject=subject)
    settings = _callback_settings()
    now = datetime.now(UTC)
    with SessionLocal() as session, session.begin():
        prior = UserSession(
            user_id=user_id,
            token_hash=hash_token(f"prior-{uuid4()}"),
            csrf_token=uuid4().hex,
            expires_at=now + timedelta(hours=1),
            last_seen_at=now,
        )
        session.add(prior)
        session.flush()
        prior_session_id = prior.id
    baseline = _session_count()
    with SessionLocal() as session:
        service = PrivilegedIdentityService(session, settings)
        _url, state = service.create_transaction(provider)
        record, raw_token, csrf, return_path = service.complete(
            provider=provider, state=state, code="valid-code"
        )
        assert record.user_id == user_id
        assert record.identity_provider == "auth0"
        assert raw_token and csrf and return_path == "/platform/pilot"
        assert record.id != prior_session_id
        first_session_id = record.id
    with SessionLocal() as session:
        with pytest.raises(PrivilegedIdentityError) as captured:
            PrivilegedIdentityService(session, settings).complete(
                provider=provider, state=state, code="valid-code"
            )
        assert captured.value.classification == "STATE_MISMATCH"
        assert session.scalar(select(func.count()).select_from(UserSession)) == baseline + 1
        assert session.get(UserSession, first_session_id) is not None
        assert session.get(UserSession, prior_session_id) is not None


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_callback_wrong_nonce_classification_consumes_state_and_creates_no_session() -> None:
    settings = _callback_settings()
    provider = _RejectingProvider("NONCE_MISMATCH")
    with SessionLocal() as session:
        baseline = _session_count()
        service = PrivilegedIdentityService(session, settings)
        _url, state = service.create_transaction(provider)
        with pytest.raises(PrivilegedIdentityError) as captured:
            service.complete(provider=provider, state=state, code="valid-code")
        assert captured.value.classification == "NONCE_MISMATCH"
        assert session.scalar(select(func.count()).select_from(UserSession)) == baseline
        transaction = session.scalars(
            select(PrivilegedAuthTransaction).where(
                PrivilegedAuthTransaction.state_hash == hash_token(state)
            )
        ).one()
        assert transaction.consumed_at is not None
        assert transaction.nonce == transaction.pkce_verifier == "consumed"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_callback_expired_state_is_consumed_without_creating_session() -> None:
    subject = f"auth0|{uuid4()}"
    _create_linked_staff(subject=subject)
    provider = _VerifiedProvider(subject=subject)
    settings = _callback_settings()
    baseline = _session_count()
    with SessionLocal() as session:
        _url, state = PrivilegedIdentityService(session, settings).create_transaction(provider)
    with SessionLocal() as session, session.begin():
        transaction = session.scalars(
            select(PrivilegedAuthTransaction).where(
                PrivilegedAuthTransaction.state_hash == hash_token(state)
            )
        ).one()
        transaction.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with SessionLocal() as session:
        with pytest.raises(PrivilegedIdentityError) as captured:
            PrivilegedIdentityService(session, settings).complete(
                provider=provider, state=state, code="valid-code"
            )
        assert captured.value.classification == "STATE_MISMATCH"
        assert session.scalar(select(func.count()).select_from(UserSession)) == baseline


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
@pytest.mark.parametrize(
    ("linked", "user_status", "membership_status", "organization_type", "classification"),
    [
        (
            False,
            UserStatus.ACTIVE,
            MembershipStatus.ACTIVE,
            OrganizationType.PLATFORM,
            "IDENTITY_NOT_LINKED",
        ),
        (
            True,
            UserStatus.DISABLED,
            MembershipStatus.ACTIVE,
            OrganizationType.PLATFORM,
            "USER_DISABLED",
        ),
        (True, UserStatus.ACTIVE, None, OrganizationType.PLATFORM, "PLATFORM_MEMBERSHIP_REQUIRED"),
        (
            True,
            UserStatus.ACTIVE,
            MembershipStatus.REVOKED,
            OrganizationType.PLATFORM,
            "PLATFORM_MEMBERSHIP_REQUIRED",
        ),
        (
            True,
            UserStatus.ACTIVE,
            MembershipStatus.ACTIVE,
            OrganizationType.CUSTOMER,
            "PLATFORM_MEMBERSHIP_REQUIRED",
        ),
    ],
)
def test_callback_identity_and_membership_failures_create_no_session(
    linked: bool,
    user_status: UserStatus,
    membership_status: MembershipStatus | None,
    organization_type: OrganizationType,
    classification: str,
) -> None:
    subject = f"auth0|{uuid4()}"
    if linked:
        _create_linked_staff(
            subject=subject,
            status=user_status,
            membership_status=membership_status,
            organization_type=organization_type,
        )
    provider = _VerifiedProvider(subject=subject)
    settings = _callback_settings()
    baseline = _session_count()
    with SessionLocal() as session:
        service = PrivilegedIdentityService(session, settings)
        _url, state = service.create_transaction(provider)
        with pytest.raises(PrivilegedIdentityError) as captured:
            service.complete(provider=provider, state=state, code="valid-code")
        assert captured.value.classification == classification
        assert session.scalar(select(func.count()).select_from(UserSession)) == baseline


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_external_identity_collision_is_rejected_by_database() -> None:
    subject = f"auth0|collision-{uuid4()}"
    _create_linked_staff(subject=subject)
    with pytest.raises(IntegrityError), SessionLocal() as session, session.begin():
        email = f"other+{uuid4().hex}@example.test"
        other = User(
            email=email,
            normalized_email=email,
            status=UserStatus.ACTIVE,
        )
        session.add(other)
        session.flush()
        session.add(
            ExternalIdentityLink(
                user_id=other.id,
                provider="auth0",
                issuer=_ISSUER,
                subject=subject,
            )
        )
        session.flush()


def _local_password_platform_client() -> TestClient:
    client = TestClient(app)
    email = f"local-platform+{uuid4().hex}@example.test"
    registration = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"}
    )
    assert registration.status_code == 201
    user_id = UUID(registration.json()["user"]["id"])
    with SessionLocal() as session, session.begin():
        org = Organization(organization_type=OrganizationType.PLATFORM, display_name="Platform")
        session.add(org)
        session.flush()
        session.add(
            OrganizationMembership(
                user_id=user_id,
                organization_id=org.id,
                role=OrganizationRole.PRODUCT_OWNER,
            )
        )
    verified = client.post(
        "/api/v1/auth/verify-email",
        json={"token": registration.json()["verification_token"]},
    )
    assert verified.status_code == 200
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "CorrectHorse12"})
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    return client


def _platform_operations() -> list[tuple[str, str]]:
    operations: list[tuple[str, str]] = []
    for method, path in sorted(enumerate_app_routes(app)):
        if not path.startswith("/api/v1/platform/"):
            continue
        safe_path = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)
        operations.append((method, safe_path))
    assert operations
    return operations


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_every_registered_platform_operation_denies_local_password_session() -> None:
    client = _local_password_platform_client()
    for method, path in _platform_operations():
        response = client.request(method, path, json={})
        assert response.status_code == 401, (method, path, response.status_code, response.text)


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_every_registered_platform_operation_denies_expired_assurance() -> None:
    client = product_owner_client()
    with SessionLocal() as session, session.begin():
        record = session.scalars(
            select(UserSession).order_by(UserSession.created_at.desc())
        ).first()
        assert record is not None
        record.assurance_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    for method, path in _platform_operations():
        response = client.request(method, path, json={})
        assert response.status_code == 401, (method, path, response.status_code, response.text)


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_mfa_does_not_override_diagnostics_role_or_active_organization() -> None:
    support = platform_role_client(OrganizationRole.PLATFORM_SUPPORT)
    assert support.get("/api/v1/platform/operations/diagnostics").status_code == 403

    owner, user_id = product_owner_client_with_user()
    with SessionLocal() as session, session.begin():
        customer_org = Organization(
            organization_type=OrganizationType.CUSTOMER, display_name="Customer context"
        )
        session.add(customer_org)
        session.flush()
        session.add(
            OrganizationMembership(
                user_id=user_id,
                organization_id=customer_org.id,
                role=OrganizationRole.CUSTOMER_OWNER,
            )
        )
        customer_org_id = customer_org.id
    response = owner.get(
        "/api/v1/platform/operations/diagnostics",
        headers={"X-Organization-Id": str(customer_org_id)},
    )
    assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_external_email_change_cannot_relink_immutable_provider_subject() -> None:
    subject = f"auth0|email-relink-{uuid4()}"
    original_user_id = _create_linked_staff(subject=subject)
    with SessionLocal() as session, session.begin():
        original = session.get(User, original_user_id, with_for_update=True)
        assert original is not None
        original.email = f"changed+{uuid4().hex}@example.test"
        original.normalized_email = original.email
        attacker_email = f"attacker+{uuid4().hex}@example.test"
        session.add(
            User(
                email=attacker_email,
                normalized_email=attacker_email,
                status=UserStatus.ACTIVE,
            )
        )
    provider = _VerifiedProvider(subject=subject)
    settings = _callback_settings()
    with SessionLocal() as session:
        service = PrivilegedIdentityService(session, settings)
        _url, state = service.create_transaction(provider)
        record, _raw, _csrf, _return_path = service.complete(
            provider=provider, state=state, code="valid-code"
        )
        assert record.user_id == original_user_id


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (OrganizationRole.PRODUCT_OWNER, 200),
        (OrganizationRole.PLATFORM_ADMIN, 200),
        (OrganizationRole.PLATFORM_SUPPORT, 403),
        (OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER, 403),
        (OrganizationRole.PLATFORM_FINANCE_REVIEWER, 403),
    ],
)
def test_mfa_assurance_preserves_diagnostics_role_matrix(
    role: OrganizationRole, expected_status: int
) -> None:
    client = platform_role_client(role)
    assert client.get("/api/v1/platform/operations/diagnostics").status_code == expected_status


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_revoked_privileged_session_is_denied_on_next_request() -> None:
    client = product_owner_client()
    with SessionLocal() as session, session.begin():
        record = session.scalars(
            select(UserSession).order_by(UserSession.created_at.desc())
        ).first()
        assert record is not None
        record.revoked_at = datetime.now(UTC)
    assert client.get("/api/v1/platform/operations/diagnostics").status_code == 401


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_platform_membership_revocation_after_login_is_immediate() -> None:
    client, user_id = product_owner_client_with_user()
    with SessionLocal() as session, session.begin():
        membership = session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        ).one()
        membership.status = MembershipStatus.REVOKED
        membership.revoked_at = datetime.now(UTC)
    assert client.get("/api/v1/platform/operations/diagnostics").status_code == 403


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
def test_user_disable_after_privileged_login_is_immediate() -> None:
    client, user_id = product_owner_client_with_user()
    with SessionLocal() as session, session.begin():
        user = session.get(User, user_id, with_for_update=True)
        assert user is not None
        user.status = UserStatus.DISABLED
    assert client.get("/api/v1/platform/operations/diagnostics").status_code == 401
