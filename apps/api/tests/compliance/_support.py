"""Shared builders for the PostgreSQL-backed compliance tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def iso(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def create_operator(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Compliance Aviation {uuid4()}",
            "country_code": "IE",
            "contact_email": f"ops-{uuid4()}@example.test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_aircraft(client: TestClient, operator_id: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator_id,
            "manufacturer": "Cessna",
            "model": "Citation CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 7,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve_admission(client: TestClient, operator_id: str) -> None:
    assert client.post(f"/api/v1/operators/{operator_id}/admission").status_code == 201
    assert client.post(f"/api/v1/operators/{operator_id}/admission/submit").status_code == 200
    response = client.post(
        f"/api/v1/operators/{operator_id}/admission/review",
        json={"action": "APPROVE", **_REVIEWER},
    )
    assert response.status_code == 200, response.text


def add_verified_evidence(
    client: TestClient,
    operator_id: str,
    evidence_type: str,
    *,
    expiry_days: int | None = 365,
    aircraft_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {"evidence_type": evidence_type, **fields}
    if aircraft_id is not None:
        body["aircraft_id"] = aircraft_id
    if expiry_days is not None:
        body["expiry_date"] = iso(expiry_days)
    evidence = client.post(f"/api/v1/operators/{operator_id}/evidence", json=body)
    assert evidence.status_code == 201, evidence.text
    evidence_id = evidence.json()["id"]
    verified = client.post(
        f"/api/v1/evidence/{evidence_id}/review", json={"action": "VERIFY", **_REVIEWER}
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def approve_authorization(client: TestClient, operator_id: str, aircraft_id: str) -> None:
    created = client.post(
        f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
        json={"authority_basis": "OWNED"},
    )
    assert created.status_code == 201, created.text
    assert (
        client.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/submit"
        ).status_code
        == 200
    )
    approved = client.post(
        f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review",
        json={"action": "APPROVE", **_REVIEWER},
    )
    assert approved.status_code == 200, approved.text


def make_operator_eligible(client: TestClient, operator_id: str, aircraft_id: str) -> None:
    """Run the full admission flow so operator+aircraft become marketplace-eligible.

    Idempotent per operator (admission + operator-level evidence added once) and
    per aircraft (authorization added once). Fixtures use this to satisfy the
    Phase 6 offer gate rather than weakening it.
    """
    if client.get(f"/api/v1/operators/{operator_id}/admission").status_code != 200:
        approve_admission(client, operator_id)
        add_verified_evidence(
            client,
            operator_id,
            "OPERATING_AUTHORITY",
            reference_number="AOC-1",
            issuing_authority="IAA",
            jurisdiction="IE",
        )
        add_verified_evidence(
            client, operator_id, "INSURANCE", insurer_name="Acme", reference_number="POL-1"
        )
    if (
        client.get(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization"
        ).status_code
        != 200
    ):
        approve_authorization(client, operator_id, aircraft_id)


def eligible_operator_aircraft(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    make_operator_eligible(client, operator["id"], aircraft["id"])
    return operator, aircraft


def create_customer(client: TestClient) -> dict[str, Any]:
    return client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Compliance Customer",
            "primary_email": f"c-{uuid4()}@example.test",
            "preferred_currency": "EUR",
            "timezone": "Europe/Dublin",
        },
    ).json()


def submitted_trip(client: TestClient, airports: list[dict[str, Any]]) -> dict[str, Any]:
    customer = create_customer(client)
    trip = client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer["id"],
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 2,
                }
            ],
        },
    ).json()
    client.post(
        f"/api/v1/trip-requests/{trip['id']}/submit", json={"expected_version": trip["version"]}
    )
    return trip


def attempt_offer(client: TestClient, trip_id: str, operator_id: str, aircraft_id: str) -> Any:
    return client.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip_id,
            "operator_id": operator_id,
            "aircraft_id": aircraft_id,
            "currency": "EUR",
            "operator_amount_minor": 1_000_000,
            "tax_amount_minor": 50_000,
            "valid_until": iso(30),
        },
    )


def pending_booking(client: TestClient, airports: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an eligible operator through to a PENDING_OPERATOR_CONFIRMATION booking."""
    operator, aircraft = eligible_operator_aircraft(client)
    trip = submitted_trip(client, airports)
    offer = attempt_offer(client, trip["id"], operator["id"], aircraft["id"]).json()
    client.post(f"/api/v1/offers/{offer['id']}/submit")
    client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    booking = client.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    ).json()
    return {
        "operator": operator,
        "aircraft": aircraft,
        "trip": trip,
        "offer": offer,
        "booking": booking,
    }


def suspend_operator(client: TestClient, operator_id: str) -> None:
    response = client.post(
        f"/api/v1/operators/{operator_id}/admission/review",
        json={
            "action": "SUSPEND",
            "actor_type": "PLATFORM_REVIEWER",
            "reason_code": "MANUAL_SUSPENSION",
        },
    )
    assert response.status_code == 200, response.text
