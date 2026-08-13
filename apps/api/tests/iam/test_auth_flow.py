"""End-to-end authentication flow (DB-backed): registration → verification → login
→ session → logout, plus CSRF, enumeration-safety, reset, and suspension."""

from __future__ import annotations

import os
from uuid import uuid4

import iam_support
import pytest

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _email() -> str:
    return f"flow+{uuid4().hex[:10]}@example.com"


@requires_db
def test_register_requires_verification_before_login() -> None:
    client = iam_support.new_client()
    email = _email()
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    assert reg.status_code == 201
    assert reg.json()["user"]["status"] == "PENDING_VERIFICATION"
    # Cannot log in until verified.
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": "CorrectHorse12"}
        ).status_code
        == 401
    )
    token = reg.json()["verification_token"]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": "CorrectHorse12"}
        ).status_code
        == 200
    )


@requires_db
def test_duplicate_email_conflicts() -> None:
    client = iam_support.new_client()
    email = _email()
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"}
        ).status_code
        == 201
    )
    dup = client.post(
        "/api/v1/auth/register", json={"email": email.upper(), "password": "CorrectHorse12"}
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "email_already_registered"


@requires_db
def test_verification_token_is_single_use() -> None:
    client = iam_support.new_client()
    reg = client.post(
        "/api/v1/auth/register", json={"email": _email(), "password": "CorrectHorse12"}
    )
    token = reg.json()["verification_token"]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400


@requires_db
def test_login_is_enumeration_safe() -> None:
    client = iam_support.new_client()
    email = _email()
    iam_support.register_verify_login(client, email=email)
    # Wrong password and unknown email return the same generic 401.
    bad_pw = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword99"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WrongPassword99"}
    )
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json()["error"]["message"] == unknown.json()["error"]["message"]


@requires_db
def test_csrf_required_for_unsafe_requests() -> None:
    client = iam_support.new_client()
    email = _email()
    iam_support.register_verify_login(client, email=email)
    saved_csrf = client.headers.pop("X-CSRF-Token")
    # Logout (POST) without the CSRF header is refused.
    assert client.post("/api/v1/auth/logout").status_code == 403
    # With the header it succeeds.
    assert (
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": saved_csrf}).status_code == 200
    )


@requires_db
def test_logout_revokes_session() -> None:
    client = iam_support.new_client()
    iam_support.register_verify_login(client)
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


@requires_db
def test_logout_all_revokes_every_session() -> None:
    email = _email()
    first = iam_support.new_client()
    iam_support.register_verify_login(first, email=email)
    second = iam_support.new_client()
    iam_support.login(second, email)  # a second session for the same user
    assert second.get("/api/v1/auth/me").status_code == 200
    assert first.post("/api/v1/auth/logout-all").status_code == 200
    # Both sessions are now invalid.
    assert first.get("/api/v1/auth/me").status_code == 401
    assert second.get("/api/v1/auth/me").status_code == 401


@requires_db
def test_password_reset_flow_and_enumeration_safety() -> None:
    from sky_bridge_jet.db.session import SessionLocal
    from sky_bridge_jet.modules.iam.services import AuthService

    client = iam_support.new_client()
    email = _email()
    iam_support.register_verify_login(client, email=email)

    # Initiation is identical for known and unknown emails.
    known = client.post("/api/v1/auth/password-reset", json={"email": email})
    unknown = client.post("/api/v1/auth/password-reset", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()

    # Drive a real reset via the service to obtain the (never-logged) token.
    with SessionLocal() as session:
        raw = AuthService(session).request_password_reset(email)
    assert raw is not None
    confirm = iam_support.new_client().post(
        "/api/v1/auth/password-reset/confirm", json={"token": raw, "password": "BrandNewPass34"}
    )
    assert confirm.status_code == 200
    # Reset revoked the old session; old client is now unauthenticated.
    assert client.get("/api/v1/auth/me").status_code == 401
    # New password works.
    fresh = iam_support.new_client()
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": email, "password": "BrandNewPass34"}
        ).status_code
        == 200
    )


@requires_db
def test_suspended_user_immediately_loses_access() -> None:
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    assert client.get("/api/v1/auth/me").status_code == 200
    iam_support.suspend_user(user_id)
    # Existing session no longer authenticates.
    assert client.get("/api/v1/auth/me").status_code == 401


@requires_db
def test_login_rate_limited() -> None:
    client = iam_support.new_client()
    email = _email()
    iam_support.register_verify_login(client, email=email)
    # Hammer with wrong credentials; the limiter (10/min) eventually returns 429.
    statuses = [
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": "WrongPassword99"}
        ).status_code
        for _ in range(15)
    ]
    assert 429 in statuses
