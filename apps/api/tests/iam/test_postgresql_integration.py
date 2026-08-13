"""Concurrency and DB-invariant tests for identity/access on real PostgreSQL."""

from __future__ import annotations

import os
import threading
from uuid import UUID

import iam_support
import pytest
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.domain import (
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
)
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership
from sky_bridge_jet.modules.iam.services import AuthService

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


@requires_db
def test_revoke_all_races_with_protected_action() -> None:
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    barrier = threading.Barrier(2)
    outcomes: list[int] = []
    lock = threading.Lock()

    def revoke() -> None:
        barrier.wait()
        with SessionLocal() as session:
            AuthService(session).logout_all(user_id)

    def act() -> None:
        barrier.wait()
        status = client.get("/api/v1/auth/me").status_code
        with lock:
            outcomes.append(status)

    threads = [threading.Thread(target=revoke), threading.Thread(target=act)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # After revoke-all, the session is unusable (no stale authorization).
    assert client.get("/api/v1/auth/me").status_code == 401


@requires_db
def test_unique_active_membership_under_concurrency() -> None:
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    with SessionLocal() as session, session.begin():
        org = Organization(
            organization_type=OrganizationType.CUSTOMER,
            display_name="Race Org",
            customer_id=None,
        )
        session.add(org)
        session.flush()
        org_id = org.id

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def grant() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session, session.begin():
                session.add(
                    OrganizationMembership(
                        user_id=user_id,
                        organization_id=org_id,
                        role=OrganizationRole.CUSTOMER_OWNER,
                    )
                )
            result = "ok"
        except IntegrityError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=grant) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with SessionLocal() as session:
        active = (
            session.query(OrganizationMembership)
            .filter(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
            .count()
        )
    assert active == 1
    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1


@requires_db
def test_role_downgrade_removes_permission_immediately() -> None:
    admin = iam_support.platform_admin_client()
    operator_id = iam_support.create_operator(admin)
    staff_client, org_id = iam_support.operator_role_client(
        operator_id, OrganizationRole.OPERATOR_ADMIN
    )
    # As operator admin, financial onboarding is permitted for its operator.
    assert (
        staff_client.post(f"/api/v1/operators/{operator_id}/financial-account").status_code == 201
    )

    # Downgrade the membership to sales (no financial permission).
    with SessionLocal() as session, session.begin():
        membership = (
            session.query(OrganizationMembership)
            .filter(OrganizationMembership.organization_id == UUID(str(org_id)))
            .one()
        )
        membership.role = OrganizationRole.OPERATOR_SALES

    # The next request immediately reflects reduced permission (principal rebuilt).
    assert (
        staff_client.post(
            f"/api/v1/operators/{operator_id}/financial-account/synchronize"
        ).status_code
        == 403
    )
