"""H1 — platform-exception security auditing (real PostgreSQL).

Proves that a successful privileged platform exception through the customer
authorization seam writes exactly one append-only ``auth_audit_log`` record with the
correct actor and safe metadata; that ordinary customers and denied attempts write
nothing; and that the write-path audit is atomic with the mutation.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.access import PLATFORM_EXCEPTION_EVENT
from sky_bridge_jet.modules.core_aviation.services import TripRequestService
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.iam.models import AuthAuditLog

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _count(*, user_id: UUID | None = None) -> int:
    with SessionLocal() as session:
        query = (
            select(func.count())
            .select_from(AuthAuditLog)
            .where(AuthAuditLog.event == PLATFORM_EXCEPTION_EVENT)
        )
        if user_id is not None:
            query = query.where(AuthAuditLog.user_id == user_id)
        return int(session.scalar(query) or 0)


def _platform_owner() -> tuple[TestClient, UUID]:
    # Grant precedes verification → no auto-provisioned personal customer (Phase 9.0.B).
    return iam_support.product_owner_client_with_user()


@requires_db
def test_platform_read_writes_one_record_with_correct_actor(admin: TestClient) -> None:
    owner_client, owner_user = _platform_owner()
    customer_id = iam_support.create_customer(admin)

    before = _count(user_id=owner_user)
    response = owner_client.get(f"/api/v1/customers/{customer_id}")
    assert response.status_code == 200
    assert _count(user_id=owner_user) == before + 1

    with SessionLocal() as session:
        record = session.scalars(
            select(AuthAuditLog)
            .where(AuthAuditLog.user_id == owner_user)
            .order_by(AuthAuditLog.created_at.desc())
        ).first()
    assert record is not None
    assert record.event == PLATFORM_EXCEPTION_EVENT  # stable event type
    assert record.user_id == owner_user  # correct actor
    assert record.organization_id is not None  # acting platform org
    assert record.detail is not None
    assert "action=getCustomer" in record.detail
    assert "permission=customer.read" in record.detail
    assert f"customer:{customer_id}" in record.detail
    # No sensitive data.
    for forbidden in ("password", "token", "csrf", "platform_fee", "operator_amount", "secret"):
        assert forbidden not in record.detail.lower()


@requires_db
def test_repeated_privileged_requests_append_separate_records(admin: TestClient) -> None:
    owner_client, owner_user = _platform_owner()
    customer_id = iam_support.create_customer(admin)
    before = _count(user_id=owner_user)
    owner_client.get(f"/api/v1/customers/{customer_id}")
    owner_client.get(f"/api/v1/customers/{customer_id}")
    owner_client.get(f"/api/v1/customers/{customer_id}")
    assert _count(user_id=owner_user) == before + 3  # append-only, never mutated


@requires_db
def test_ordinary_customer_in_own_tenant_writes_no_event(admin: TestClient) -> None:
    customer_id = iam_support.create_customer(admin)
    client, _ = iam_support.customer_owner_client(admin, customer_id)
    before = _count()
    assert client.get(f"/api/v1/customers/{customer_id}").status_code == 200
    assert (
        client.post(
            "/api/v1/passengers",
            json={"customer_id": str(customer_id), "first_name": "Ada", "last_name": "B"},
        ).status_code
        == 201
    )
    assert _count() == before  # no platform-exception event for own-tenant access


@requires_db
def test_denied_cross_tenant_customer_writes_no_success_event(admin: TestClient) -> None:
    a_id = iam_support.create_customer(admin)
    b_id = iam_support.create_customer(admin)
    a_client, _ = iam_support.customer_owner_client(admin, a_id)
    before = _count()
    assert a_client.get(f"/api/v1/customers/{b_id}").status_code == 404
    assert _count() == before  # a denial never records a successful exception


@requires_db
def test_operator_cannot_reach_platform_exception_branch(admin: TestClient) -> None:
    operator_id = iam_support.create_operator(admin)
    op_client, _ = iam_support.operator_role_client(operator_id, OrganizationRole.OPERATOR_ADMIN)
    customer_id = iam_support.create_customer(admin)
    before = _count()
    # An operator has neither customer ownership nor a platform role → denied, no event.
    assert op_client.get(f"/api/v1/customers/{customer_id}").status_code == 404
    assert (
        op_client.post(
            "/api/v1/passengers",
            json={"customer_id": str(customer_id), "first_name": "X", "last_name": "Y"},
        ).status_code
        == 403
    )
    assert _count() == before


@requires_db
def test_platform_write_creates_record_atomically(admin: TestClient) -> None:
    owner_client, owner_user = _platform_owner()
    customer_id = iam_support.create_customer(admin)
    before = _count(user_id=owner_user)
    created = owner_client.post(
        "/api/v1/passengers",
        json={"customer_id": str(customer_id), "first_name": "Grace", "last_name": "H"},
    )
    assert created.status_code == 201
    # The passenger and its audit committed together.
    assert _count(user_id=owner_user) == before + 1


@requires_db
def test_failed_mutation_writes_no_audit_record(admin: TestClient) -> None:
    """A privileged write that fails its lifecycle guard leaves no audit record."""
    owner_client, owner_user = _platform_owner()
    customer_id = iam_support.create_customer(admin)
    trip = owner_client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": str(customer_id),
            "legs": [
                {
                    "origin_airport_id": str(uuid4()),
                    "destination_airport_id": str(uuid4()),
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 1,
                }
            ],
        },
    )
    # The trip create itself fails (unknown airports) → no trip, and its audit rolled
    # back with the mutation.
    assert trip.status_code in (404, 409, 422)
    # A submit against a stale/absent version also fails and records nothing.
    before = _count(user_id=owner_user)
    submitted = owner_client.post(
        f"/api/v1/trip-requests/{uuid4()}/submit", json={"expected_version": 999}
    )
    assert submitted.status_code == 404
    assert _count(user_id=owner_user) == before


@requires_db
def test_write_audit_rolls_back_with_the_mutation(admin: TestClient, airports: list) -> None:
    """Direct service-level proof: if the audit hook fails, the mutation rolls back too."""
    customer_id = iam_support.create_customer(admin)
    trip = admin.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": str(customer_id),
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 1,
                }
            ],
        },
    ).json()

    def _boom(_session: object) -> None:
        raise RuntimeError("audit failure")

    with SessionLocal() as session, pytest.raises(RuntimeError):
        TripRequestService(session).submit(
            UUID(trip["id"]), expected_version=trip["version"], on_commit=_boom
        )
    # The submit rolled back with the failing audit: the trip is still DRAFT.
    after = admin.get(f"/api/v1/trip-requests/{trip['id']}").json()
    assert after["status"] == "DRAFT"
