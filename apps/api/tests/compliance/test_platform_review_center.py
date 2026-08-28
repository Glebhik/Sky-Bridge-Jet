from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.compliance.domain import (
    AircraftAuthorizationStatus,
    AuthorityBasis,
    EvidenceStatus,
    EvidenceType,
    OperatorAdmissionStatus,
)
from sky_bridge_jet.modules.compliance.models import (
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.compliance.services import ComplianceService
from sky_bridge_jet.modules.core_aviation.domain import AircraftCategory
from sky_bridge_jet.modules.core_aviation.models import Aircraft, Operator
from sky_bridge_jet.modules.iam.domain import OrganizationRole

from ._support import create_aircraft, create_operator, requires_db

pytestmark = requires_db


def test_platform_queues_are_bounded_safe_and_discoverable(client: TestClient) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    admission = client.post(f"/api/v1/operators/{operator['id']}/admission").json()
    client.post(f"/api/v1/operators/{operator['id']}/admission/submit")
    evidence = client.post(
        f"/api/v1/operators/{operator['id']}/evidence",
        json={
            "evidence_type": "INSURANCE",
            "reference_number": "SAFE-REF",
            "storage_object_reference": "private/bucket/object.pdf",
        },
    ).json()
    authorization = client.post(
        f"/api/v1/operators/{operator['id']}/aircraft/{aircraft['id']}/authorization",
        json={"authority_basis": "OWNED"},
    ).json()
    client.post(
        f"/api/v1/operators/{operator['id']}/aircraft/{aircraft['id']}/authorization/submit"
    )

    reviewer = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    try:
        admissions = reviewer.get(
            "/api/v1/platform/compliance/admissions",
            params={"status": "SUBMITTED", "limit": 100, "offset": 0},
        )
        assert admissions.status_code == 200
        assert any(row["id"] == admission["id"] for row in admissions.json())
        evidence_queue = reviewer.get(
            "/api/v1/platform/compliance/evidence",
            params={"status": "SUBMITTED", "limit": 100, "offset": 0},
        )
        item = next(row for row in evidence_queue.json() if row["id"] == evidence["id"])
        assert item["has_storage_object"] is True
        serialized = str(item)
        for forbidden in ("storage_object_reference", "private/bucket", "customer", "payment"):
            assert forbidden not in serialized.lower()
        authorizations = reviewer.get(
            "/api/v1/platform/compliance/aircraft-authorizations",
            params={"status": "SUBMITTED", "limit": 100, "offset": 0},
        ).json()
        assert any(row["id"] == authorization["id"] for row in authorizations)
        assert (
            reviewer.get(
                "/api/v1/platform/compliance/admissions", params={"limit": 101}
            ).status_code
            == 422
        )
    finally:
        reviewer.close()


def test_platform_queue_query_count_is_constant(client: TestClient) -> None:
    for _ in range(4):
        operator = create_operator(client)
        client.post(f"/api/v1/operators/{operator['id']}/admission")
        client.post(f"/api/v1/operators/{operator['id']}/admission/submit")

    statements = 0

    def count_statement(*_args: object, **_kwargs: object) -> None:
        nonlocal statements
        statements += 1

    with SessionLocal() as session:
        event.listen(session.bind, "before_cursor_execute", count_statement)
        try:
            rows = ComplianceService(session).list_platform_admissions(
                status=None, limit=100, offset=0
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
    assert len(rows) >= 4
    assert statements == 1


def test_platform_large_authorization_queue_is_bounded_stable_and_constant_query(
    client: TestClient,
) -> None:
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        operators: list[Operator] = []
        aircraft_rows: list[Aircraft] = []
        admissions: list[OperatorAdmission] = []
        evidence_rows: list[ComplianceEvidence] = []
        authorizations: list[OperatorAircraftAuthorization] = []
        for index in range(150):
            operator_id = uuid4()
            aircraft_id = uuid4()
            operators.append(
                Operator(
                    id=operator_id,
                    legal_name=f"Queue Operator {index:03d} {operator_id}",
                    country_code="IE",
                    contact_email=f"queue-{operator_id}@example.test",
                )
            )
            aircraft_rows.append(
                Aircraft(
                    id=aircraft_id,
                    operator_id=operator_id,
                    manufacturer="Cessna",
                    model="Citation CJ3+",
                    category=AircraftCategory.LIGHT_JET,
                    registration=f"Q{uuid4().hex[:7].upper()}",
                    passenger_capacity=7,
                )
            )
            admissions.append(
                OperatorAdmission(
                    operator_id=operator_id,
                    status=OperatorAdmissionStatus.SUBMITTED,
                    submitted_at=now,
                )
            )
            evidence_rows.append(
                ComplianceEvidence(
                    operator_id=operator_id,
                    evidence_type=EvidenceType.INSURANCE,
                    status=EvidenceStatus.SUBMITTED,
                    submitted_at=now,
                )
            )
            authorizations.append(
                OperatorAircraftAuthorization(
                    operator_id=operator_id,
                    aircraft_id=aircraft_id,
                    status=AircraftAuthorizationStatus.SUBMITTED,
                    authority_basis=AuthorityBasis.OWNED,
                    submitted_at=now,
                )
            )
        session.add_all(operators)
        session.flush()
        session.add_all(aircraft_rows)
        session.flush()
        session.add_all(admissions)
        session.add_all(evidence_rows)
        session.add_all(authorizations)
        session.flush()
        created_authorization_ids = {row.id for row in authorizations}

    with SessionLocal() as session:
        service = ComplianceService(session)
        first = service.list_platform_authorizations(
            status=AircraftAuthorizationStatus.SUBMITTED, limit=100, offset=0
        )
        second = service.list_platform_authorizations(
            status=AircraftAuthorizationStatus.SUBMITTED, limit=100, offset=100
        )
        repeated = service.list_platform_authorizations(
            status=AircraftAuthorizationStatus.SUBMITTED, limit=100, offset=0
        )
        assert len(first) == 100
        assert 50 <= len(second) <= 100
        assert [row.authorization.id for row in first] == [row.authorization.id for row in repeated]
        assert {row.authorization.id for row in first}.isdisjoint(
            row.authorization.id for row in second
        )
        assert created_authorization_ids.issubset(
            {row.authorization.id for row in (*first, *second)}
        )

        for loader in (
            service.list_platform_admissions,
            service.list_platform_evidence,
            service.list_platform_authorizations,
        ):
            for limit in (1, 20, 100):
                statements = 0

                def count_statement(*_args: object, **_kwargs: object) -> None:
                    nonlocal statements
                    statements += 1

                event.listen(session.bind, "before_cursor_execute", count_statement)
                try:
                    rows = loader(status=None, limit=limit, offset=0)
                finally:
                    event.remove(session.bind, "before_cursor_execute", count_statement)
                assert len(rows) == limit
                assert statements == 1


def test_platform_review_paths_cannot_mutate_a_different_resource(
    client: TestClient,
) -> None:
    operator_a = create_operator(client)
    operator_b = create_operator(client)
    aircraft_a = create_aircraft(client, operator_a["id"])
    aircraft_b = create_aircraft(client, operator_b["id"])
    admission_a = client.post(f"/api/v1/operators/{operator_a['id']}/admission").json()
    admission_b = client.post(f"/api/v1/operators/{operator_b['id']}/admission").json()
    client.post(f"/api/v1/operators/{operator_a['id']}/admission/submit")
    client.post(f"/api/v1/operators/{operator_b['id']}/admission/submit")
    evidence_a = client.post(
        f"/api/v1/operators/{operator_a['id']}/evidence",
        json={"evidence_type": "INSURANCE"},
    ).json()
    evidence_b = client.post(
        f"/api/v1/operators/{operator_b['id']}/evidence",
        json={"evidence_type": "INSURANCE"},
    ).json()
    authorization_a = client.post(
        f"/api/v1/operators/{operator_a['id']}/aircraft/{aircraft_a['id']}/authorization",
        json={"authority_basis": "OWNED"},
    ).json()
    authorization_b = client.post(
        f"/api/v1/operators/{operator_b['id']}/aircraft/{aircraft_b['id']}/authorization",
        json={"authority_basis": "OWNED"},
    ).json()
    client.post(
        f"/api/v1/operators/{operator_a['id']}/aircraft/{aircraft_a['id']}/authorization/submit"
    )
    client.post(
        f"/api/v1/operators/{operator_b['id']}/aircraft/{aircraft_b['id']}/authorization/submit"
    )

    reviewer = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    try:
        cases = (
            ("admissions", admission_a["id"], admission_b["id"]),
            ("evidence", evidence_a["id"], evidence_b["id"]),
            (
                "aircraft-authorizations",
                authorization_a["id"],
                authorization_b["id"],
            ),
        )
        for kind, target_id, other_id in cases:
            response = reviewer.post(
                f"/api/v1/platform/compliance/{kind}/{target_id}/review",
                json={"action": "BEGIN_REVIEW"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["id"] == target_id
            assert response.json()["status"] == "UNDER_REVIEW"
            untouched = reviewer.get(f"/api/v1/platform/compliance/{kind}/{other_id}")
            assert untouched.status_code == 200
            assert untouched.json()["id"] == other_id
            assert untouched.json()["status"] == "SUBMITTED"
            other_events = reviewer.get(
                f"/api/v1/platform/compliance/{kind}/{other_id}/audit-events"
            ).json()
            assert all(event["action"] != "REVIEW_STARTED" for event in other_events)
    finally:
        reviewer.close()


def test_platform_decision_actor_is_server_derived_and_roles_fail_closed(
    client: TestClient,
) -> None:
    operator = create_operator(client)
    admission = client.post(f"/api/v1/operators/{operator['id']}/admission").json()
    client.post(f"/api/v1/operators/{operator['id']}/admission/submit")

    finance = iam_support.platform_role_client(OrganizationRole.PLATFORM_FINANCE_REVIEWER)
    reviewer = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    reviewer_id = reviewer.get("/api/v1/auth/me").json()["user"]["id"]
    try:
        path = f"/api/v1/platform/compliance/admissions/{admission['id']}/review"
        assert finance.get("/api/v1/platform/compliance/admissions").status_code == 403
        assert finance.post(path, json={"action": "BEGIN_REVIEW"}).status_code == 403
        reviewed = reviewer.post(path, json={"action": "BEGIN_REVIEW"})
        assert reviewed.status_code == 200
        events = reviewer.get(
            f"/api/v1/platform/compliance/admissions/{admission['id']}/audit-events"
        ).json()
        assert events[-1]["actor_type"] == "PLATFORM_REVIEWER"
        assert events[-1]["actor_reference"] == reviewer_id
        for field in (
            "actor_type",
            "actor_reference",
            "reviewer_id",
            "actor_id",
            "platform_actor_id",
            "organization_id",
            "operator_id",
        ):
            injected = reviewer.post(path, json={"action": "APPROVE", field: "fake"})
            assert injected.status_code == 422
    finally:
        finance.close()
        reviewer.close()


@pytest.mark.parametrize(
    "role",
    [
        OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER,
        OrganizationRole.PLATFORM_ADMIN,
        OrganizationRole.PRODUCT_OWNER,
    ],
)
def test_platform_compliance_allowed_role_matrix(
    client: TestClient, role: OrganizationRole
) -> None:
    operator = create_operator(client)
    admission = client.post(f"/api/v1/operators/{operator['id']}/admission").json()
    client.post(f"/api/v1/operators/{operator['id']}/admission/submit")
    role_client = iam_support.platform_role_client(role)
    try:
        assert role_client.get("/api/v1/platform/compliance/admissions").status_code == 200
        reviewed = role_client.post(
            f"/api/v1/platform/compliance/admissions/{admission['id']}/review",
            json={"action": "BEGIN_REVIEW"},
        )
        assert reviewed.status_code == 200, reviewed.text
        events = role_client.get(
            f"/api/v1/platform/compliance/admissions/{admission['id']}/audit-events"
        ).json()
        expected_actor = (
            "PRODUCT_OWNER" if role is OrganizationRole.PRODUCT_OWNER else "PLATFORM_REVIEWER"
        )
        assert events[-1]["actor_type"] == expected_actor
    finally:
        role_client.close()


@pytest.mark.parametrize(
    "role",
    [
        OrganizationRole.PLATFORM_SUPPORT,
        OrganizationRole.PLATFORM_FINANCE_REVIEWER,
    ],
)
def test_platform_compliance_denied_platform_role_matrix(
    client: TestClient, role: OrganizationRole
) -> None:
    operator = create_operator(client)
    admission = client.post(f"/api/v1/operators/{operator['id']}/admission").json()
    client.post(f"/api/v1/operators/{operator['id']}/admission/submit")
    path = f"/api/v1/platform/compliance/admissions/{admission['id']}/review"
    role_client = iam_support.platform_role_client(role)
    try:
        assert role_client.get("/api/v1/platform/compliance/admissions").status_code == 403
        assert role_client.post(path, json={"action": "BEGIN_REVIEW"}).status_code == 403
    finally:
        role_client.close()


@pytest.mark.parametrize("principal_kind", ["customer", "operator", "anonymous"])
def test_platform_compliance_non_platform_principals_fail_closed(
    client: TestClient, principal_kind: str
) -> None:
    operator = create_operator(client)
    admission = client.post(f"/api/v1/operators/{operator['id']}/admission").json()
    client.post(f"/api/v1/operators/{operator['id']}/admission/submit")
    path = f"/api/v1/platform/compliance/admissions/{admission['id']}/review"
    if principal_kind == "customer":
        customer_id = iam_support.create_customer(client)
        principal, _ = iam_support.customer_owner_client(client, customer_id)
        expected = 403
    elif principal_kind == "operator":
        principal, _ = iam_support.operator_role_client(
            UUID(operator["id"]), OrganizationRole.OPERATOR_ADMIN
        )
        expected = 403
    else:
        principal = iam_support.new_client()
        expected = 401
    try:
        assert principal.get("/api/v1/platform/compliance/admissions").status_code == expected
        assert principal.post(path, json={"action": "BEGIN_REVIEW"}).status_code == expected
    finally:
        principal.close()
