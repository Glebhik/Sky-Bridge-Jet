"""Shared builders for the PostgreSQL-backed operator-offer tests.

The single-selected-offer invariant relies on a PostgreSQL partial unique index,
which has no SQLite equivalent, so these tests run against a real database.
"""

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


def future_iso(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def create_customer(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Offer Customer",
            "primary_email": f"offer-{uuid4()}@example.test",
            "preferred_currency": "EUR",
            "timezone": "Europe/Dublin",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_operator(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Example Aviation {uuid4()}",
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
    aircraft = response.json()
    # Phase 6 gate: the operator+aircraft must be marketplace-eligible before any
    # offer can be created. Fixtures satisfy the gate rather than weakening it.
    make_operator_eligible(client, operator_id, aircraft["id"])
    return aircraft


_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def make_operator_eligible(client: TestClient, operator_id: str, aircraft_id: str) -> None:
    """Admit the operator and authorize the aircraft so offer creation is allowed."""
    if client.get(f"/api/v1/operators/{operator_id}/admission").status_code != 200:
        assert client.post(f"/api/v1/operators/{operator_id}/admission").status_code == 201
        assert client.post(f"/api/v1/operators/{operator_id}/admission/submit").status_code == 200
        assert (
            client.post(
                f"/api/v1/operators/{operator_id}/admission/review",
                json={"action": "APPROVE", **_REVIEWER},
            ).status_code
            == 200
        )
        for body in (
            {
                "evidence_type": "OPERATING_AUTHORITY",
                "reference_number": "AOC-1",
                "issuing_authority": "IAA",
                "jurisdiction": "IE",
                "expiry_date": future_iso(365),
            },
            {
                "evidence_type": "INSURANCE",
                "insurer_name": "Acme",
                "reference_number": "POL-1",
                "expiry_date": future_iso(365),
            },
        ):
            evidence = client.post(f"/api/v1/operators/{operator_id}/evidence", json=body).json()
            client.post(
                f"/api/v1/evidence/{evidence['id']}/review",
                json={"action": "VERIFY", **_REVIEWER},
            )
    if (
        client.get(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization"
        ).status_code
        != 200
    ):
        client.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
            json={"authority_basis": "OWNED"},
        )
        client.post(f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/submit")
        client.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review",
            json={"action": "APPROVE", **_REVIEWER},
        )


def submitted_trip(client: TestClient, customer_id: str, airports: list[dict[str, Any]]) -> dict:
    trip = client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer_id,
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
    submitted = client.post(
        f"/api/v1/trip-requests/{trip['id']}/submit",
        json={"expected_version": trip["version"]},
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def offer_payload(
    *, trip_request_id: str, operator_id: str, aircraft_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "trip_request_id": trip_request_id,
        "operator_id": operator_id,
        "aircraft_id": aircraft_id,
        "currency": "EUR",
        "operator_amount_minor": 1_000_000,
        "tax_amount_minor": 0,
        "valid_until": future_iso(),
    }
    payload.update(overrides)
    return payload
