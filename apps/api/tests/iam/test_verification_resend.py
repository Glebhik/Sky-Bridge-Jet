"""Phase 9.2.A — verification-resend contract (DB-backed).

`POST /api/v1/auth/verification/resend` lets a customer recover from a lost or expired
verification email. It is enumeration-safe: the public response is identical for every
input (unknown, malformed, ACTIVE, suspended, or eligible pending), and it never returns
a token. Only a still-``PENDING_VERIFICATION`` account is issued a fresh token; issuing a
replacement invalidates any prior unused token so exactly one verification path is live.
The endpoint is rate-limited per IP and never alters membership/tenancy.
"""

from __future__ import annotations

import os
from uuid import uuid4

import iam_support
import pytest
from sqlalchemy import func, select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.models import (
    AuthAuditLog,
    EmailVerificationToken,
    OrganizationMembership,
    User,
)
from sky_bridge_jet.modules.iam.services import AuthService

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_PUBLIC_MESSAGE = "If the account requires verification, verification instructions have been sent"


def _email() -> str:
    return f"resend+{uuid4().hex[:10]}@example.com"


def _register(client, email: str) -> None:
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    assert reg.status_code == 201, reg.text


def _resend(client, email: str):
    return client.post("/api/v1/auth/verification/resend", json={"email": email})


def _live_token_count(user_id) -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(EmailVerificationToken)
                .where(
                    EmailVerificationToken.user_id == user_id,
                    EmailVerificationToken.consumed_at.is_(None),
                )
            )
            or 0
        )


def test_resend_unknown_email_is_acknowledged_without_disclosure() -> None:
    # No DB row is needed: an unknown email must return the same public acknowledgement.
    resp = _resend(iam_support.new_client(), _email())
    assert resp.status_code == 200
    assert resp.json()["message"] == _PUBLIC_MESSAGE


def test_resend_malformed_email_is_acknowledged_identically() -> None:
    resp = _resend(iam_support.new_client(), "not-an-email")
    assert resp.status_code == 200
    assert resp.json()["message"] == _PUBLIC_MESSAGE


@requires_db
def test_resend_never_returns_a_token_and_message_is_uniform() -> None:
    client = iam_support.new_client()
    pending = _email()
    _register(client, pending)
    for email in (pending, _email(), "still-not-an-email"):
        resp = _resend(client, email)
        assert resp.status_code == 200
        assert resp.json() == {"message": _PUBLIC_MESSAGE}
        assert "token" not in resp.text.lower()


@requires_db
def test_resend_for_pending_user_issues_a_new_valid_token_and_invalidates_the_old() -> None:
    client = iam_support.new_client()
    email = _email()
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    original_token = reg.json()["verification_token"]
    with SessionLocal() as session:
        user_id = session.scalars(select(User).where(User.normalized_email == email)).one().id

    assert _resend(client, email).status_code == 200
    # Exactly one live (unconsumed) verification token remains — the replacement.
    assert _live_token_count(user_id) == 1

    # The original token is now invalid; the newly issued one verifies the account. The
    # new raw token is obtained through the service (never the HTTP response).
    assert (
        client.post("/api/v1/auth/verify-email", json={"token": original_token}).status_code == 400
    )
    fresh = AuthService(SessionLocal()).resend_verification(email)
    assert fresh is not None
    assert client.post("/api/v1/auth/verify-email", json={"token": fresh}).status_code == 200


@requires_db
def test_resend_for_active_user_is_acknowledged_but_issues_nothing() -> None:
    client = iam_support.new_client()
    email = _email()
    user_id = iam_support.register_verify_login(client, email=email)  # now ACTIVE + provisioned
    before_memberships = _membership_count(user_id)

    assert _resend(client, email).status_code == 200
    # No verification token is issued for an already-active account, and tenancy is intact.
    assert _live_token_count(user_id) == 0
    assert _membership_count(user_id) == before_memberships
    # The service itself signals ineligibility with None (no token for the mailer).
    assert AuthService(SessionLocal()).resend_verification(email) is None


@requires_db
def test_resend_for_suspended_user_is_acknowledged_but_issues_nothing() -> None:
    from sky_bridge_jet.modules.iam.domain import UserStatus

    client = iam_support.new_client()
    email = _email()
    _register(client, email)
    with SessionLocal() as session, session.begin():
        user = session.scalars(select(User).where(User.normalized_email == email)).one()
        user.status = UserStatus.SUSPENDED
        user_id = user.id

    assert _resend(client, email).status_code == 200
    assert _live_token_count(user_id) == 1  # the original registration token, untouched
    assert AuthService(SessionLocal()).resend_verification(email) is None


def test_resend_is_rate_limited_per_ip() -> None:
    client = iam_support.new_client()
    statuses = [_resend(client, _email()).status_code for _ in range(6)]
    assert statuses[5] == 429


@requires_db
def test_resend_writes_a_safe_audit_record_without_secrets() -> None:
    client = iam_support.new_client()
    email = _email()
    _register(client, email)
    with SessionLocal() as session:
        user_id = session.scalars(select(User).where(User.normalized_email == email)).one().id
    assert _resend(client, email).status_code == 200
    with SessionLocal() as session:
        records = list(
            session.scalars(
                select(AuthAuditLog).where(
                    AuthAuditLog.user_id == user_id,
                    AuthAuditLog.event == "verification_resent",
                )
            ).all()
        )
    assert len(records) == 1
    detail = (records[0].detail or "").lower()
    for forbidden in ("token", "password", "secret", "@"):
        assert forbidden not in detail


def _membership_count(user_id) -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(OrganizationMembership.user_id == user_id)
            )
            or 0
        )
