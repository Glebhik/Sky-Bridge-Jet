from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from ._support import (
    add_verified_evidence,
    approve_admission,
    approve_authorization,
    attempt_offer,
    create_aircraft,
    create_operator,
    eligible_operator_aircraft,
    pending_booking,
    requires_db,
    submitted_trip,
    suspend_operator,
)

pytestmark = requires_db
_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def _gate_reasons(response: Any) -> set[str]:
    body = response.json()
    assert body["error"]["code"] == "compliance_not_satisfied", body
    return {detail["reason"] for detail in body["error"]["details"]}


# -- Offer gate -------------------------------------------------------------


def test_offer_blocked_for_unreviewed_operator(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])  # no admission/authorization
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], operator["id"], aircraft["id"])
    assert response.status_code == 409
    assert "OPERATOR_NOT_ADMITTED" in _gate_reasons(response)


def test_offer_blocked_for_rejected_operator(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    oid = operator["id"]
    client.post(f"/api/v1/operators/{oid}/admission")
    client.post(f"/api/v1/operators/{oid}/admission/submit")
    client.post(
        f"/api/v1/operators/{oid}/admission/review",
        json={"action": "REJECT", "reason_code": "AUTHORITY_NOT_VERIFIED", **_REVIEWER},
    )
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], oid, aircraft["id"])
    assert response.status_code == 409
    assert "OPERATOR_REJECTED" in _gate_reasons(response)


def test_offer_blocked_for_suspended_operator(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator, aircraft = eligible_operator_aircraft(client)
    suspend_operator(client, operator["id"])
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], operator["id"], aircraft["id"])
    assert response.status_code == 409
    assert "OPERATOR_SUSPENDED" in _gate_reasons(response)


def test_offer_blocked_for_expired_authority(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    oid = operator["id"]
    approve_admission(client, oid)
    add_verified_evidence(client, oid, "OPERATING_AUTHORITY", expiry_days=-1, reference_number="A")
    add_verified_evidence(client, oid, "INSURANCE", insurer_name="Acme")
    approve_authorization(client, oid, aircraft["id"])
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], oid, aircraft["id"])
    assert response.status_code == 409
    assert "AUTHORITY_EXPIRED" in _gate_reasons(response)


def test_offer_blocked_for_expired_insurance(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    oid = operator["id"]
    approve_admission(client, oid)
    add_verified_evidence(client, oid, "OPERATING_AUTHORITY", reference_number="A")
    add_verified_evidence(client, oid, "INSURANCE", expiry_days=-1, insurer_name="Acme")
    approve_authorization(client, oid, aircraft["id"])
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], oid, aircraft["id"])
    assert response.status_code == 409
    assert "INSURANCE_EXPIRED" in _gate_reasons(response)


def test_offer_blocked_for_unapproved_aircraft(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    oid = operator["id"]
    approve_admission(client, oid)
    add_verified_evidence(client, oid, "OPERATING_AUTHORITY", reference_number="A")
    add_verified_evidence(client, oid, "INSURANCE", insurer_name="Acme")
    # No aircraft authorization.
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], oid, aircraft["id"])
    assert response.status_code == 409
    assert "AIRCRAFT_NOT_AUTHORIZED" in _gate_reasons(response)


def test_offer_allowed_for_fully_eligible_combination(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator, aircraft = eligible_operator_aircraft(client)
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], operator["id"], aircraft["id"])
    assert response.status_code == 201, response.text


# -- Booking confirmation recheck -------------------------------------------


def test_booking_confirmation_blocked_on_compliance_lapse(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = pending_booking(client, airports)
    suspend_operator(client, scenario["operator"]["id"])

    confirm = client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert confirm.status_code == 409
    assert "OPERATOR_SUSPENDED" in _gate_reasons(confirm)

    # Booking is not mutated; history preserved.
    booking = client.get(f"/api/v1/bookings/{scenario['booking']['id']}").json()
    assert booking["status"] == "PENDING_OPERATOR_CONFIRMATION"


# -- Payment interaction ----------------------------------------------------


def test_authorized_payment_then_lapse_blocks_confirmation_and_capture(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = pending_booking(client, airports)
    booking_id = scenario["booking"]["id"]
    payment = client.post(f"/api/v1/bookings/{booking_id}/payment").json()
    authorized = client.post(
        f"/api/v1/payments/{payment['id']}/authorize",
        json={"idempotency_key": f"authz-{uuid4()}"},
    )
    assert authorized.json()["status"] == "AUTHORIZED"

    suspend_operator(client, scenario["operator"]["id"])

    # Confirmation blocked by compliance recheck.
    confirm = client.post(
        f"/api/v1/bookings/{booking_id}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert confirm.status_code == 409
    # Capture is impossible because the booking is not confirmed (no auto refund/void).
    capture = client.post(
        f"/api/v1/payments/{payment['id']}/capture", json={"idempotency_key": f"cap-{uuid4()}"}
    )
    assert capture.status_code == 409
    assert capture.json()["error"]["code"] == "payment_not_allowed"
    assert client.get(f"/api/v1/payments/{payment['id']}").json()["status"] == "AUTHORIZED"


# -- Suspension preserves history -------------------------------------------


def test_suspension_blocks_new_offers_but_preserves_existing(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator, aircraft = eligible_operator_aircraft(client)
    trip = submitted_trip(client, airports)
    existing = attempt_offer(client, trip["id"], operator["id"], aircraft["id"])
    assert existing.status_code == 201
    existing_id = existing.json()["id"]

    suspend_operator(client, operator["id"])

    # New offer blocked.
    trip2 = submitted_trip(client, airports)
    blocked = attempt_offer(client, trip2["id"], operator["id"], aircraft["id"])
    assert blocked.status_code == 409

    # Existing offer preserved and retrievable, unchanged.
    preserved = client.get(f"/api/v1/offers/{existing_id}")
    assert preserved.status_code == 200
    assert preserved.json()["status"] == "DRAFT"


def test_restore_after_suspension_reenables_offers(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator, aircraft = eligible_operator_aircraft(client)
    oid = operator["id"]
    suspend_operator(client, oid)
    client.post(
        f"/api/v1/operators/{oid}/admission/review", json={"action": "RESTORE", **_REVIEWER}
    )
    trip = submitted_trip(client, airports)
    response = attempt_offer(client, trip["id"], oid, aircraft["id"])
    assert response.status_code == 201
