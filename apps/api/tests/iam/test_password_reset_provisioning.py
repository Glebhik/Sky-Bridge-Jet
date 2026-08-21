"""Phase 9.2.A — password-reset customer-provisioning consistency (DB-backed).

Completing a password reset proves control of the email address, so a
``PENDING_VERIFICATION`` user is activated exactly as email verification would activate
them. To keep the two trusted email-control paths consistent, reset now runs the same
canonical ``provision_personal_customer`` service — idempotently, honouring invitation
and existing-membership precedence, and only on the pending→active transition. A reset
for an already-active user creates no additional tenancy, and reset still revokes every
existing session.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import iam_support
import pytest
from sqlalchemy import func, select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.core_aviation.models import Customer
from sky_bridge_jet.modules.iam.domain import (
    InvitationStatus,
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
    UserSession,
)
from sky_bridge_jet.modules.iam.services import AuthService

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_NEW_PASSWORD = "BrandNewPass34"


def _email() -> str:
    return f"reset+{uuid4().hex[:10]}@example.com"


def _register_pending(client, email: str) -> UUID:
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    assert reg.status_code == 201, reg.text
    return UUID(reg.json()["user"]["id"])


def _reset_password(client, email: str, password: str = _NEW_PASSWORD) -> None:
    """Drive a real reset via the service to obtain the (never-logged) token, then confirm."""
    with SessionLocal() as session:
        raw = AuthService(session).request_password_reset(email)
    assert raw is not None
    resp = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": raw, "password": password}
    )
    assert resp.status_code == 200, resp.text


def _customer_org_count(user_id: UUID) -> tuple[int, int, int]:
    """(CUSTOMER_OWNER memberships, CUSTOMER orgs owned, customers) for a user."""
    with SessionLocal() as session:
        memberships = list(
            session.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                    OrganizationMembership.role == OrganizationRole.CUSTOMER_OWNER,
                )
            ).all()
        )
        org_ids = [m.organization_id for m in memberships]
        orgs = (
            list(
                session.scalars(
                    select(Organization).where(
                        Organization.id.in_(org_ids),
                        Organization.organization_type == OrganizationType.CUSTOMER,
                    )
                ).all()
            )
            if org_ids
            else []
        )
        customer_ids = [o.customer_id for o in orgs if o.customer_id is not None]
        customers = (
            int(
                session.scalar(
                    select(func.count()).select_from(Customer).where(Customer.id.in_(customer_ids))
                )
                or 0
            )
            if customer_ids
            else 0
        )
        return len(memberships), len(orgs), customers


@requires_db
def test_pending_user_reset_activates_and_provisions_personal_customer() -> None:
    client = iam_support.new_client()
    email = _email()
    user_id = _register_pending(client, email)
    assert _customer_org_count(user_id) == (0, 0, 0)  # nothing before reset

    _reset_password(client, email)

    with SessionLocal() as session:
        assert session.get(User, user_id).status is UserStatus.ACTIVE
    # Activated via reset now yields the same canonical personal customer tenant.
    assert _customer_org_count(user_id) == (1, 1, 1)
    # And the freshly reset user can actually sign in and resolve their own reads.
    iam_support.login(client, email, _NEW_PASSWORD)
    assert client.get("/api/v1/me/bookings").status_code == 200


@requires_db
def test_pending_user_with_valid_invitation_is_not_personally_provisioned_on_reset() -> None:
    admin = iam_support.product_owner_client()
    operator_id = iam_support.create_operator(admin)
    email = _email()
    normalized = email.strip().lower()
    with SessionLocal() as session, session.begin():
        org = Organization(
            organization_type=OrganizationType.OPERATOR,
            display_name="Inviting Operator",
            operator_id=operator_id,
        )
        session.add(org)
        session.flush()
        session.add(
            OrganizationInvitation(
                organization_id=org.id,
                invited_email_normalized=normalized,
                role=OrganizationRole.OPERATOR_SALES,
                token_hash=uuid4().hex,
                status=InvitationStatus.PENDING,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

    client = iam_support.new_client()
    user_id = _register_pending(client, email)
    _reset_password(client, email)

    with SessionLocal() as session:
        assert session.get(User, user_id).status is UserStatus.ACTIVE
    # Invitation precedence is preserved: no personal customer tenant is created.
    assert _customer_org_count(user_id) == (0, 0, 0)


@requires_db
def test_reset_for_already_active_provisioned_user_creates_no_duplicate_tenancy() -> None:
    client = iam_support.new_client()
    email = _email()
    user_id = iam_support.register_verify_login(client, email=email)  # ACTIVE + provisioned (1,1,1)
    assert _customer_org_count(user_id) == (1, 1, 1)

    _reset_password(client, email)

    with SessionLocal() as session:
        assert session.get(User, user_id).status is UserStatus.ACTIVE
    # A mere password change on an already-active user adds no tenancy.
    assert _customer_org_count(user_id) == (1, 1, 1)


@requires_db
def test_reset_revokes_all_existing_sessions() -> None:
    client = iam_support.new_client()
    email = _email()
    iam_support.register_verify_login(client, email=email)  # logs in → live session
    # The active session can reach a protected route before the reset.
    assert client.get("/api/v1/auth/me").status_code == 200

    _reset_password(client, email)

    # Every prior session is revoked; the old cookie no longer authenticates.
    assert client.get("/api/v1/auth/me").status_code == 401
    with SessionLocal() as session:
        user_id = session.scalars(select(User).where(User.normalized_email == email)).one().id
        live = session.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        )
    assert live == 0
    # And the user can sign in again with the new password.
    iam_support.login(client, email, _NEW_PASSWORD)


@requires_db
def test_reset_provisioning_is_atomic_on_provisioning_failure(monkeypatch) -> None:
    """If provisioning fails mid-reset, the whole reset transaction rolls back.

    The user must not be left activated-but-passwordless-changed with no tenant: the
    single transaction guarantees all-or-nothing.
    """
    from fastapi.testclient import TestClient

    import sky_bridge_jet.modules.iam.services as services
    from sky_bridge_jet.main import app

    client = iam_support.new_client()
    email = _email()
    user_id = _register_pending(client, email)

    def _boom(*args, **kwargs):
        raise RuntimeError("provisioning failure injected")

    monkeypatch.setattr(services, "provision_personal_customer", _boom)

    with SessionLocal() as session:
        raw = AuthService(session).request_password_reset(email)
    assert raw is not None
    # A non-raising client so the unhandled failure surfaces as a 500 response rather than
    # being re-raised into the test; the point under test is the transactional rollback.
    non_raising = TestClient(app, raise_server_exceptions=False)
    resp = non_raising.post(
        "/api/v1/auth/password-reset/confirm", json={"token": raw, "password": _NEW_PASSWORD}
    )
    assert resp.status_code == 500

    # Rolled back: still pending, no tenant, and the reset token was not consumed.
    with SessionLocal() as session:
        assert session.get(User, user_id).status is UserStatus.PENDING_VERIFICATION
    assert _customer_org_count(user_id) == (0, 0, 0)
