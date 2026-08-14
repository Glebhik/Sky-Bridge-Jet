"""Phase 9.0.A-2 (H) — operator platform-exception security auditing (real PostgreSQL).

Proves that a successful privileged platform exception through the operator
authorization seam writes exactly one append-only ``auth_audit_log`` record with the
correct actor and safe metadata; that ordinary operators and denied attempts write
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
from sky_bridge_jet.modules.core_aviation.models import Aircraft
from sky_bridge_jet.modules.core_aviation.schemas import AircraftCreate
from sky_bridge_jet.modules.core_aviation.services import OperatorService
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
    # Grant precedes verification, so this platform product-owner has no auto-provisioned
    # personal customer tenant (Phase 9.0.B).
    return iam_support.product_owner_client_with_user()


def _aircraft_count(operator_id: UUID) -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(Aircraft)
                .where(Aircraft.operator_id == operator_id)
            )
            or 0
        )


@requires_db
def test_platform_read_writes_one_record_with_correct_actor(admin: TestClient) -> None:
    owner_client, owner_user = _platform_owner()
    operator_id = iam_support.create_operator(admin)

    before = _count(user_id=owner_user)
    response = owner_client.get(f"/api/v1/operators/{operator_id}")
    assert response.status_code == 200
    assert _count(user_id=owner_user) == before + 1

    with SessionLocal() as session:
        record = session.scalars(
            select(AuthAuditLog)
            .where(AuthAuditLog.user_id == owner_user)
            .order_by(AuthAuditLog.created_at.desc())
        ).first()
    assert record is not None
    assert record.event == PLATFORM_EXCEPTION_EVENT
    assert record.user_id == owner_user
    assert record.organization_id is not None  # acting platform org
    assert record.detail is not None
    assert "action=getOperator" in record.detail
    assert "permission=operator.read" in record.detail
    assert f"operator:{operator_id}" in record.detail
    for forbidden in ("password", "token", "csrf", "platform_fee", "operator_amount", "secret"):
        assert forbidden not in record.detail.lower()


@requires_db
def test_repeated_privileged_reads_append_separate_records(admin: TestClient) -> None:
    owner_client, owner_user = _platform_owner()
    operator_id = iam_support.create_operator(admin)
    before = _count(user_id=owner_user)
    owner_client.get(f"/api/v1/operators/{operator_id}")
    owner_client.get(f"/api/v1/operators/{operator_id}")
    owner_client.get(f"/api/v1/operators/{operator_id}")
    assert _count(user_id=owner_user) == before + 3  # append-only, never mutated


@requires_db
def test_ordinary_operator_in_own_tenant_writes_no_event(admin: TestClient) -> None:
    operator_id = iam_support.create_operator(admin)
    client, _ = iam_support.operator_role_client(operator_id, OrganizationRole.OPERATOR_ADMIN)
    before = _count()
    assert client.get(f"/api/v1/operators/{operator_id}").status_code == 200
    assert client.post(f"/api/v1/operators/{operator_id}/admission").status_code == 201
    assert _count() == before  # own-tenant operator action is never an exception


@requires_db
def test_denied_cross_operator_writes_no_success_event(admin: TestClient) -> None:
    a_id = iam_support.create_operator(admin)
    b_id = iam_support.create_operator(admin)
    a_client, _ = iam_support.operator_role_client(a_id, OrganizationRole.OPERATOR_ADMIN)
    before = _count()
    assert a_client.get(f"/api/v1/operators/{b_id}").status_code == 404
    assert _count() == before  # a denial never records a successful exception


@requires_db
def test_customer_cannot_reach_platform_exception_branch(admin: TestClient) -> None:
    operator_id = iam_support.create_operator(admin)
    customer_client, _ = iam_support.customer_owner_client(
        admin, iam_support.create_customer(admin)
    )
    before = _count()
    # A customer has neither operator membership nor a platform role → denied, no event.
    assert customer_client.get(f"/api/v1/operators/{operator_id}").status_code == 404
    assert _count() == before


@requires_db
def test_platform_write_creates_record_atomically(admin: TestClient) -> None:
    owner_client, owner_user = _platform_owner()
    operator_id = iam_support.create_operator(admin)
    before = _count(user_id=owner_user)
    created = owner_client.post(
        "/api/v1/aircraft",
        json={
            "operator_id": str(operator_id),
            "manufacturer": "Gulfstream",
            "model": "G280",
            "category": "MIDSIZE_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 8,
        },
    )
    assert created.status_code == 201, created.text
    # The aircraft and its audit committed together.
    assert _count(user_id=owner_user) == before + 1


@requires_db
def test_failed_mutation_writes_no_audit_record(admin: TestClient, airports: list) -> None:
    """A privileged write that fails leaves no audit record (aircraft not of operator)."""
    owner_client, owner_user = _platform_owner()
    a = iam_support.full_booking_scenario(admin, airports, confirm=False)
    other_operator = iam_support.create_operator(admin)
    before = _count(user_id=owner_user)
    # Aircraft belongs to `a`'s operator, not `other_operator` → concealed 404, no record.
    denied = owner_client.post(
        f"/api/v1/operators/{other_operator}/aircraft/{a['aircraft_id']}/authorization",
        json={"authority_basis": "OWNED"},
    )
    assert denied.status_code == 404
    assert _count(user_id=owner_user) == before


@requires_db
def test_write_audit_rolls_back_with_the_mutation(admin: TestClient) -> None:
    """Direct service-level proof: if the audit hook fails, the mutation rolls back too."""
    operator_id = iam_support.create_operator(admin)

    def _boom(_session: object) -> None:
        raise RuntimeError("audit failure")

    data = AircraftCreate.model_validate(
        {
            "operator_id": str(operator_id),
            "manufacturer": "Dassault",
            "model": "Falcon 2000",
            "category": "SUPER_MIDSIZE_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 10,
        }
    )
    with SessionLocal() as session, pytest.raises(RuntimeError):
        OperatorService(session).create_aircraft(data, on_commit=_boom)
    # The failing audit rolled the aircraft insert back: none exists for the operator.
    assert _aircraft_count(operator_id) == 0
