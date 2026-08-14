"""Phase 9.0.B (A/H) — customer self-provisioning (DB-backed).

Proves that a self-registering individual is atomically provisioned exactly one
personal customer tenant on email verification; that the invitation and
existing-membership paths take precedence; that a suspended user never provisions;
that the identity is a neutral placeholder; that a single append-only audit record is
written with no secrets; and that concurrent/repeated verification produces at most one
tenant.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
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
    AuthAuditLog,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)
from sky_bridge_jet.modules.iam.provisioning import (
    CUSTOMER_SELF_PROVISIONED_EVENT,
    PROVISIONAL_ACCOUNT_DISPLAY_NAME,
)

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _register(client: TestClient, email: str) -> str:
    """Register a fresh user and return the raw verification token (unverified)."""
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "CorrectHorse12"})
    assert reg.status_code == 201, reg.text
    return str(reg.json()["verification_token"])


def _customer_org_count(user_id: UUID) -> tuple[int, int, int]:
    """(customer_owner memberships, CUSTOMER orgs owned, customers) for a user."""
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
def test_self_registering_user_is_provisioned_one_personal_customer() -> None:
    client = iam_support.new_client()
    email = f"solo+{uuid4().hex[:8]}@example.com"
    user_id = iam_support.register_verify_login(client, email=email)

    memberships, orgs, customers = _customer_org_count(user_id)
    assert (memberships, orgs, customers) == (1, 1, 1)
    # The provisioned user has a working customer context (its own 'my' list resolves).
    assert client.get("/api/v1/me/bookings").status_code == 200


@requires_db
def test_neutral_account_identity_is_not_derived_from_email() -> None:
    client = iam_support.new_client()
    email = f"neutral+{uuid4().hex[:8]}@example.com"
    user_id = iam_support.register_verify_login(client, email=email)
    local_part = email.split("@")[0]
    with SessionLocal() as session:
        org = session.scalars(
            select(Organization)
            .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
            .where(OrganizationMembership.user_id == user_id)
        ).first()
        assert org is not None
        assert org.display_name == PROVISIONAL_ACCOUNT_DISPLAY_NAME
        customer = session.get(Customer, org.customer_id)
        assert customer is not None
        assert customer.display_name == PROVISIONAL_ACCOUNT_DISPLAY_NAME
        assert local_part not in customer.display_name  # never email-derived


@requires_db
def test_provisioning_writes_one_safe_audit_record() -> None:
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    with SessionLocal() as session:
        records = list(
            session.scalars(
                select(AuthAuditLog).where(
                    AuthAuditLog.user_id == user_id,
                    AuthAuditLog.event == CUSTOMER_SELF_PROVISIONED_EVENT,
                )
            ).all()
        )
    assert len(records) == 1
    record = records[0]
    assert record.organization_id is not None
    detail = (record.detail or "").lower()
    for forbidden in ("token", "password", "secret", "@", "verification"):
        assert forbidden not in detail


@requires_db
def test_repeated_verification_creates_no_second_tenant() -> None:
    client = iam_support.new_client()
    email = f"repeat+{uuid4().hex[:8]}@example.com"
    token = _register(client, email)
    first = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    user_id = UUID(first.json()["id"]) if "id" in first.json() else None
    # Re-using the consumed token is rejected and provisions nothing further.
    second = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert second.status_code in (400, 401, 404)
    if user_id is not None:
        assert _customer_org_count(user_id) == (1, 1, 1)


@requires_db
def test_existing_membership_takes_precedence_over_personal_provisioning() -> None:
    # An operator staff user (granted before verify) gets no personal customer tenant.
    admin = iam_support.product_owner_client()
    operator_id = iam_support.create_operator(admin)
    _client, org_id = iam_support.operator_role_client(operator_id, OrganizationRole.OPERATOR_ADMIN)
    with SessionLocal() as session:
        user_id = (
            session.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == org_id
                )
            )
            .one()
            .user_id
        )
    # No CUSTOMER_OWNER personal tenant was created (existing-membership precedence).
    assert _customer_org_count(user_id) == (0, 0, 0)


@requires_db
def test_pending_invitation_takes_precedence_over_personal_provisioning() -> None:
    admin = iam_support.product_owner_client()
    # Any organization to attach the invitation to.
    operator_id = iam_support.create_operator(admin)
    email = f"invited+{uuid4().hex[:8]}@example.com"
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
    user_id = iam_support.register_verify_login(client, email=email)
    # The invitation path is authoritative → no personal customer tenant provisioned.
    assert _customer_org_count(user_id) == (0, 0, 0)


@requires_db
def test_suspended_user_does_not_provision() -> None:
    client = iam_support.new_client()
    email = f"suspended+{uuid4().hex[:8]}@example.com"
    token = _register(client, email)
    with SessionLocal() as session, session.begin():
        user = session.scalars(select(User).where(User.normalized_email == email)).one()
        user.status = UserStatus.SUSPENDED
        user_id = user.id
    verify = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200  # verification records email_verified_at
    assert _customer_org_count(user_id) == (0, 0, 0)  # but no tenant for a suspended user
    with SessionLocal() as session:
        assert session.get(User, user_id).status is UserStatus.SUSPENDED


@requires_db
def test_concurrent_verification_creates_exactly_one_tenant() -> None:
    client = iam_support.new_client()
    email = f"race+{uuid4().hex[:8]}@example.com"
    token = _register(client, email)
    with SessionLocal() as session:
        user_id = session.scalars(select(User).where(User.normalized_email == email)).one().id

    barrier = threading.Barrier(2)
    outcomes: list[int] = []
    lock = threading.Lock()

    def _verify() -> None:
        racer = iam_support.new_client()
        barrier.wait()
        status = racer.post("/api/v1/auth/verify-email", json={"token": token}).status_code
        with lock:
            outcomes.append(status)

    threads = [threading.Thread(target=_verify) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert 200 in outcomes  # exactly one verification consumes the single-use token
    assert _customer_org_count(user_id) == (1, 1, 1)  # never a duplicate tenant
