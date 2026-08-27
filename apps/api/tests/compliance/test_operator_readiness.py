from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.compliance.services import ComplianceService
from sky_bridge_jet.modules.core_aviation.models import Aircraft, TripRequest
from sky_bridge_jet.modules.financials.models import ProviderWebhookEvent
from sky_bridge_jet.modules.iam.domain import OrganizationRole, OrganizationType
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership
from sky_bridge_jet.modules.iam.router import _register_limiter
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation

from ._support import add_verified_evidence, approve_admission, create_operator

_PATH = "/api/v1/me/operator-compliance-readiness"
_FIELDS = {
    "admission_status",
    "marketplace_eligible",
    "blockers",
    "created_at",
    "updated_at",
}
_ROLES = (
    OrganizationRole.OPERATOR_ADMIN,
    OrganizationRole.OPERATOR_SALES,
    OrganizationRole.OPERATOR_OPERATIONS,
    OrganizationRole.OPERATOR_FINANCE,
    OrganizationRole.OPERATOR_COMPLIANCE,
)


def _actor(operator_id: str, role: OrganizationRole) -> TestClient:
    _register_limiter.clear()
    with SessionLocal() as session:
        organization_id = (
            session.query(Organization.id).filter_by(operator_id=UUID(operator_id)).scalar()
        )
    if organization_id is None:
        actor, organization_id = iam_support.operator_role_client(UUID(operator_id), role)
    else:
        actor = iam_support.member_client_for_org(organization_id, role)
    actor.headers["X-Organization-Id"] = str(organization_id)
    return actor


def _counts() -> tuple[int, ...]:
    with SessionLocal() as session:
        return tuple(
            session.query(model).count()
            for model in (
                OperatorAdmission,
                ComplianceEvidence,
                OperatorAircraftAuthorization,
                Aircraft,
                OperatorOffer,
                TripRequest,
                Payment,
                PaymentOperation,
                ComplianceAuditEvent,
                ProviderWebhookEvent,
            )
        )


def _admission(client: TestClient, operator_id: str, status: str) -> None:
    assert client.post(f"/api/v1/operators/{operator_id}/admission").status_code == 201
    if status == "DRAFT":
        return
    assert client.post(f"/api/v1/operators/{operator_id}/admission/submit").status_code == 200
    if status == "SUBMITTED":
        return
    action = {
        "UNDER_REVIEW": "BEGIN_REVIEW",
        "REJECTED": "REJECT",
    }[status]
    response = client.post(
        f"/api/v1/operators/{operator_id}/admission/review",
        json={"action": action, "actor_type": "PLATFORM_REVIEWER", "note": "private"},
    )
    assert response.status_code == 200, response.text


def test_auth_roles_and_exact_safe_projection(client: TestClient) -> None:
    anonymous = iam_support.new_client()
    assert anonymous.get(_PATH).status_code == 401
    anonymous.close()

    customer = iam_support.new_client()
    _register_limiter.clear()
    iam_support.register_verify_login(customer)
    assert customer.get(_PATH).status_code == 403
    customer.close()

    operator = create_operator(client)
    for role in _ROLES:
        actor = _actor(operator["id"], role)
        response = actor.get(_PATH)
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == _FIELDS
        assert body == {
            "admission_status": None,
            "marketplace_eligible": False,
            "blockers": [
                "OPERATOR_NOT_ADMITTED",
                "AUTHORITY_NOT_VERIFIED",
                "INSURANCE_NOT_VERIFIED",
            ],
            "created_at": None,
            "updated_at": None,
        }
        serialized = response.text.lower()
        for forbidden in (
            "operator_id",
            "review_note",
            "reviewer",
            "storage_object_reference",
            "evidence",
            "aircraft",
            "customer",
            "passenger",
            "payment",
            "provider",
        ):
            assert forbidden not in serialized
        actor.close()


@pytest.mark.parametrize(
    ("status", "expected_blocker"),
    (
        ("DRAFT", "OPERATOR_NOT_ADMITTED"),
        ("SUBMITTED", "OPERATOR_NOT_ADMITTED"),
        ("UNDER_REVIEW", "OPERATOR_UNDER_REVIEW"),
        ("REJECTED", "OPERATOR_REJECTED"),
    ),
)
def test_admission_state_matrix(client: TestClient, status: str, expected_blocker: str) -> None:
    operator = create_operator(client)
    _admission(client, operator["id"], status)
    actor = _actor(operator["id"], OrganizationRole.OPERATOR_COMPLIANCE)
    body = actor.get(_PATH).json()
    assert body["admission_status"] == status
    assert body["marketplace_eligible"] is False
    assert body["blockers"][0] == expected_blocker
    assert body["created_at"] is not None and body["updated_at"] is not None
    assert "private" not in str(body)
    actor.close()


def test_eligibility_expiry_and_suspension_follow_canonical_evaluator(client: TestClient) -> None:
    eligible = create_operator(client)
    approve_admission(client, eligible["id"])
    add_verified_evidence(client, eligible["id"], "OPERATING_AUTHORITY")
    add_verified_evidence(client, eligible["id"], "INSURANCE")
    actor = _actor(eligible["id"], OrganizationRole.OPERATOR_ADMIN)
    assert actor.get(_PATH).json()["marketplace_eligible"] is True
    assert actor.get(_PATH).json()["blockers"] == []
    actor.close()

    expired = create_operator(client)
    approve_admission(client, expired["id"])
    add_verified_evidence(client, expired["id"], "OPERATING_AUTHORITY", expiry_days=-1)
    add_verified_evidence(client, expired["id"], "INSURANCE")
    actor = _actor(expired["id"], OrganizationRole.OPERATOR_SALES)
    body = actor.get(_PATH).json()
    assert body["admission_status"] == "APPROVED"
    assert body["marketplace_eligible"] is False
    assert body["blockers"] == ["AUTHORITY_EXPIRED"]
    actor.close()

    suspended = create_operator(client)
    approve_admission(client, suspended["id"])
    add_verified_evidence(client, suspended["id"], "OPERATING_AUTHORITY")
    add_verified_evidence(client, suspended["id"], "INSURANCE")
    response = client.post(
        f"/api/v1/operators/{suspended['id']}/admission/review",
        json={"action": "SUSPEND", "actor_type": "PLATFORM_REVIEWER", "note": "private"},
    )
    assert response.status_code == 200
    actor = _actor(suspended["id"], OrganizationRole.OPERATOR_OPERATIONS)
    body = actor.get(_PATH).json()
    assert body["admission_status"] == "SUSPENDED"
    assert body["marketplace_eligible"] is False
    assert body["blockers"] == ["OPERATOR_SUSPENDED"]
    assert "private" not in str(body)
    actor.close()


def test_active_organization_isolation_and_no_operator_oracle(client: TestClient) -> None:
    operator_a = create_operator(client)
    operator_b = create_operator(client)
    approve_admission(client, operator_b["id"])
    add_verified_evidence(client, operator_b["id"], "OPERATING_AUTHORITY")
    add_verified_evidence(client, operator_b["id"], "INSURANCE")

    actor = iam_support.new_client()
    _register_limiter.clear()
    organizations: dict[str, UUID] = {}

    def grant(user_id: UUID) -> None:
        with SessionLocal() as session, session.begin():
            for label, operator_id in (("a", operator_a["id"]), ("b", operator_b["id"])):
                organization = Organization(
                    organization_type=OrganizationType.OPERATOR,
                    display_name=f"Operator {label.upper()}",
                    operator_id=UUID(operator_id),
                )
                session.add(organization)
                session.flush()
                organizations[label] = organization.id
                session.add(
                    OrganizationMembership(
                        user_id=user_id,
                        organization_id=organization.id,
                        role=OrganizationRole.OPERATOR_SALES,
                    )
                )

    iam_support.register_verify_login(actor, before_verify=grant)
    assert actor.get(_PATH).status_code == 403
    actor.headers["X-Organization-Id"] = str(organizations["a"])
    assert actor.get(_PATH).json()["marketplace_eligible"] is False
    actor.headers["X-Organization-Id"] = str(organizations["b"])
    assert actor.get(_PATH).json()["marketplace_eligible"] is True
    actor.headers["X-Organization-Id"] = str(organizations["a"])
    assert (
        actor.get(f"{_PATH}?operator_id={operator_b['id']}").json()["marketplace_eligible"] is False
    )
    actor.headers["X-Organization-Id"] = str(uuid4())
    assert actor.get(_PATH).status_code == 403
    actor.close()


def test_service_is_fixed_query_and_read_only(client: TestClient) -> None:
    operator = create_operator(client)
    before = _counts()
    statements = 0

    def count_statement(*_args: Any, **_kwargs: Any) -> None:
        nonlocal statements
        statements += 1

    with SessionLocal() as session:
        event.listen(session.bind, "before_cursor_execute", count_statement)
        try:
            admission, decision = ComplianceService(session).operator_readiness(
                UUID(operator["id"])
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
    assert admission is None
    assert decision.eligible is False
    assert statements == 5
    assert _counts() == before


def test_large_evidence_history_has_bounded_queries_and_zero_orm_materialization(
    client: TestClient,
) -> None:
    operator = create_operator(client)
    operator_id = UUID(operator["id"])
    now = datetime.now(UTC)
    rows = [
        {
            "id": uuid4(),
            "operator_id": operator_id,
            "aircraft_id": None,
            "evidence_type": evidence_type,
            "status": "VERIFIED",
            "expiry_date": now - timedelta(days=index + 1),
            "submitted_at": now - timedelta(days=index + 2),
        }
        for evidence_type in ("OPERATING_AUTHORITY", "INSURANCE")
        for index in range(600)
    ]
    rows.extend(
        (
            {
                "id": uuid4(),
                "operator_id": operator_id,
                "aircraft_id": None,
                "evidence_type": "OPERATING_AUTHORITY",
                "status": "VERIFIED",
                "expiry_date": now + timedelta(days=30),
                "submitted_at": now - timedelta(days=1),
            },
            {
                "id": uuid4(),
                "operator_id": operator_id,
                "aircraft_id": None,
                "evidence_type": "OPERATING_AUTHORITY",
                "status": "SUBMITTED",
                "expiry_date": now + timedelta(days=60),
                "submitted_at": now,
            },
        )
    )
    with SessionLocal() as session, session.begin():
        session.execute(insert(ComplianceEvidence), rows)

    statements = 0
    materialized = 0

    def count_statement(*_args: Any, **_kwargs: Any) -> None:
        nonlocal statements
        statements += 1

    def count_load(*_args: Any, **_kwargs: Any) -> None:
        nonlocal materialized
        materialized += 1

    with SessionLocal() as session:
        event.listen(session.bind, "before_cursor_execute", count_statement)
        event.listen(ComplianceEvidence, "load", count_load)
        try:
            _, decision = ComplianceService(session).operator_readiness(operator_id)
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
            event.remove(ComplianceEvidence, "load", count_load)

    assert decision.eligible is False
    assert [reason.value for reason in decision.reasons] == [
        "OPERATOR_NOT_ADMITTED",
        "INSURANCE_EXPIRED",
    ]
    assert statements == 5
    assert materialized == 0


def test_openapi_has_one_selector_free_safe_get(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][_PATH]
    assert set(operation) == {"get"}
    get = operation["get"]
    assert get["operationId"] == "getMyOperatorComplianceReadiness"
    assert "requestBody" not in get
    assert [parameter["name"] for parameter in get.get("parameters", [])] == ["x-organization-id"]
    schema = get["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("OperatorComplianceReadinessResponse")
    projection = client.get("/openapi.json").json()["components"]["schemas"][
        "OperatorComplianceReadinessResponse"
    ]["properties"]
    assert set(projection) == _FIELDS
