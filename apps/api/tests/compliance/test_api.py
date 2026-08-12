from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from ._support import (
    add_verified_evidence,
    approve_admission,
    approve_authorization,
    create_aircraft,
    create_operator,
    eligible_operator_aircraft,
    iso,
    requires_db,
)

pytestmark = requires_db
_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def test_admission_lifecycle_and_audit(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]

    created = client.post(f"/api/v1/operators/{oid}/admission")
    assert created.status_code == 201
    assert created.json()["status"] == "DRAFT"

    assert client.post(f"/api/v1/operators/{oid}/admission/submit").json()["status"] == "SUBMITTED"
    approved = client.post(
        f"/api/v1/operators/{oid}/admission/review", json={"action": "APPROVE", **_REVIEWER}
    )
    assert approved.json()["status"] == "APPROVED"

    suspended = client.post(
        f"/api/v1/operators/{oid}/admission/review",
        json={"action": "SUSPEND", "reason_code": "MANUAL_SUSPENSION", **_REVIEWER},
    )
    assert suspended.json()["status"] == "SUSPENDED"
    restored = client.post(
        f"/api/v1/operators/{oid}/admission/review", json={"action": "RESTORE", **_REVIEWER}
    )
    assert restored.json()["status"] == "APPROVED"

    events = client.get(f"/api/v1/operators/{oid}/admission/audit-events").json()
    actions = [event["action"] for event in events]
    assert actions == ["CREATED", "SUBMITTED", "APPROVED", "SUSPENDED", "RESTORED"]
    assert events[2]["actor_type"] == "PLATFORM_REVIEWER"
    assert events[3]["reason_code"] == "MANUAL_SUSPENSION"


def test_admission_illegal_transition_rejected(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]
    client.post(f"/api/v1/operators/{oid}/admission")  # DRAFT
    response = client.post(
        f"/api/v1/operators/{oid}/admission/review", json={"action": "APPROVE", **_REVIEWER}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_compliance_state"


def test_review_requires_human_authorized_actor(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]
    client.post(f"/api/v1/operators/{oid}/admission")
    client.post(f"/api/v1/operators/{oid}/admission/submit")
    for bad_actor in ("SYSTEM", "OPERATOR"):
        response = client.post(
            f"/api/v1/operators/{oid}/admission/review",
            json={"action": "APPROVE", "actor_type": bad_actor},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "review_actor_not_permitted"


def test_duplicate_admission_rejected(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]
    assert client.post(f"/api/v1/operators/{oid}/admission").status_code == 201
    assert client.post(f"/api/v1/operators/{oid}/admission").status_code == 409


def test_evidence_lifecycle_and_effective_expiration(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]

    submitted = client.post(
        f"/api/v1/operators/{oid}/evidence",
        json={"evidence_type": "INSURANCE", "insurer_name": "Acme", "expiry_date": iso(365)},
    )
    assert submitted.status_code == 201
    body = submitted.json()
    assert body["status"] == "SUBMITTED"
    assert body["effective_status"] == "SUBMITTED"

    verified = client.post(
        f"/api/v1/evidence/{body['id']}/review", json={"action": "VERIFY", **_REVIEWER}
    )
    assert verified.json()["effective_status"] == "VERIFIED"

    # Verified but past expiry → effective EXPIRED.
    expired = add_verified_evidence(
        client, oid, "OPERATING_AUTHORITY", expiry_days=-1, reference_number="OLD"
    )
    assert expired["status"] == "VERIFIED"
    assert client.get(f"/api/v1/evidence/{expired['id']}").json()["effective_status"] == "EXPIRED"


def test_evidence_supersession_preserves_history(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]
    first = add_verified_evidence(client, oid, "INSURANCE", insurer_name="Acme")

    second = client.post(
        f"/api/v1/operators/{oid}/evidence",
        json={
            "evidence_type": "INSURANCE",
            "insurer_name": "Acme",
            "expiry_date": iso(365),
            "supersedes_evidence_id": first["id"],
        },
    )
    assert second.status_code == 201
    superseded = client.get(f"/api/v1/evidence/{first['id']}").json()
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_id"] == second.json()["id"]


def test_authorization_lifecycle(client: TestClient) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    oid, aid = operator["id"], aircraft["id"]

    created = client.post(
        f"/api/v1/operators/{oid}/aircraft/{aid}/authorization",
        json={"authority_basis": "LEASED"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "DRAFT"
    assert (
        client.post(f"/api/v1/operators/{oid}/aircraft/{aid}/authorization/submit").json()["status"]
        == "SUBMITTED"
    )
    approved = client.post(
        f"/api/v1/operators/{oid}/aircraft/{aid}/authorization/review",
        json={"action": "APPROVE", **_REVIEWER},
    )
    assert approved.json()["status"] == "APPROVED"


def test_operator_eligibility_is_explainable(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]

    before = client.get(f"/api/v1/operators/{oid}/eligibility").json()
    assert before["eligible"] is False
    assert set(before["reasons"]) == {
        "OPERATOR_NOT_ADMITTED",
        "AUTHORITY_NOT_VERIFIED",
        "INSURANCE_NOT_VERIFIED",
    }

    approve_admission(client, oid)
    add_verified_evidence(client, oid, "OPERATING_AUTHORITY", reference_number="AOC-1")
    add_verified_evidence(client, oid, "INSURANCE", insurer_name="Acme")
    after = client.get(f"/api/v1/operators/{oid}/eligibility").json()
    assert after["eligible"] is True
    assert after["reasons"] == []


def test_operator_aircraft_eligibility(client: TestClient) -> None:
    operator = create_operator(client)
    oid = operator["id"]
    aircraft = create_aircraft(client, oid)
    aid = aircraft["id"]
    approve_admission(client, oid)
    add_verified_evidence(client, oid, "OPERATING_AUTHORITY", reference_number="AOC-1")
    add_verified_evidence(client, oid, "INSURANCE", insurer_name="Acme")

    unauthorized = client.get(f"/api/v1/operators/{oid}/aircraft/{aid}/eligibility").json()
    assert unauthorized["eligible"] is False
    assert unauthorized["reasons"] == ["AIRCRAFT_NOT_AUTHORIZED"]

    approve_authorization(client, oid, aid)
    authorized = client.get(f"/api/v1/operators/{oid}/aircraft/{aid}/eligibility").json()
    assert authorized["eligible"] is True


def test_eligibility_for_unknown_operator_returns_404(client: TestClient) -> None:
    assert (
        client.get("/api/v1/operators/00000000-0000-0000-0000-000000000000/eligibility").status_code
        == 404
    )


def test_make_operator_eligible_helper(client: TestClient, airports: list[dict[str, Any]]) -> None:
    operator, aircraft = eligible_operator_aircraft(client)
    decision = client.get(
        f"/api/v1/operators/{operator['id']}/aircraft/{aircraft['id']}/eligibility"
    ).json()
    assert decision["eligible"] is True
