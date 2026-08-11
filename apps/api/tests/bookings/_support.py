"""Shared builders for the PostgreSQL-backed booking tests.

Booking invariants (one active booking per trip) rely on a PostgreSQL partial
unique index with no SQLite equivalent, so these tests run against a real
database.
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


def _future_iso(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def create_customer(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Booking Customer",
            "primary_email": f"booking-{uuid4()}@example.test",
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
            "legal_name": f"Booking Aviation {uuid4()}",
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


def submitted_trip(
    client: TestClient, customer_id: str, airports: list[dict[str, Any]]
) -> dict[str, Any]:
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


def draft_offer(
    client: TestClient,
    *,
    trip_request_id: str,
    operator_id: str,
    aircraft_id: str,
    valid_until: str | None = None,
    operator_amount_minor: int = 1_000_000,
    tax_amount_minor: int = 50_000,
    currency: str = "EUR",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip_request_id,
            "operator_id": operator_id,
            "aircraft_id": aircraft_id,
            "currency": currency,
            "operator_amount_minor": operator_amount_minor,
            "tax_amount_minor": tax_amount_minor,
            "valid_until": valid_until or _future_iso(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def selected_offer(
    client: TestClient,
    *,
    trip_request_id: str,
    operator_id: str,
    aircraft_id: str,
    **offer_kwargs: Any,
) -> dict[str, Any]:
    """Create, submit, and select an offer, returning the selected offer."""
    offer = draft_offer(
        client,
        trip_request_id=trip_request_id,
        operator_id=operator_id,
        aircraft_id=aircraft_id,
        **offer_kwargs,
    )
    assert client.post(f"/api/v1/offers/{offer['id']}/submit").status_code == 200
    selected = client.post(f"/api/v1/trip-requests/{trip_request_id}/offers/{offer['id']}/select")
    assert selected.status_code == 200, selected.text
    return selected.json()


def booking_scenario(
    client: TestClient, airports: list[dict[str, Any]], **offer_kwargs: Any
) -> dict[str, Any]:
    """Build a full customer→operator→aircraft→trip→selected-offer scenario."""
    customer = create_customer(client)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    trip = submitted_trip(client, customer["id"], airports)
    offer = selected_offer(
        client,
        trip_request_id=trip["id"],
        operator_id=operator["id"],
        aircraft_id=aircraft["id"],
        **offer_kwargs,
    )
    return {
        "customer": customer,
        "operator": operator,
        "aircraft": aircraft,
        "trip": trip,
        "offer": offer,
    }


def create_booking(client: TestClient, scenario: dict[str, Any]) -> Any:
    return client.post(
        "/api/v1/bookings",
        json={
            "trip_request_id": scenario["trip"]["id"],
            "operator_offer_id": scenario["offer"]["id"],
        },
    )
