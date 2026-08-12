"""Shared builders for the PostgreSQL-backed payment tests.

Payment financial invariants (idempotency keys, captured<=authorized) rely on
PostgreSQL constraints and row locking, so these tests run against a real
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


def new_key() -> str:
    return f"idem-{uuid4()}"


_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def _eligibility_expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=365)).isoformat()


def make_operator_eligible(client: TestClient, operator_id: str, aircraft_id: str) -> None:
    """Admit the operator and authorize the aircraft so offer creation is allowed."""
    if client.get(f"/api/v1/operators/{operator_id}/admission").status_code != 200:
        client.post(f"/api/v1/operators/{operator_id}/admission")
        client.post(f"/api/v1/operators/{operator_id}/admission/submit")
        client.post(
            f"/api/v1/operators/{operator_id}/admission/review",
            json={"action": "APPROVE", **_REVIEWER},
        )
        for body in (
            {
                "evidence_type": "OPERATING_AUTHORITY",
                "reference_number": "AOC-1",
                "issuing_authority": "IAA",
                "jurisdiction": "IE",
                "expiry_date": _eligibility_expiry(),
            },
            {
                "evidence_type": "INSURANCE",
                "insurer_name": "Acme",
                "reference_number": "POL-1",
                "expiry_date": _eligibility_expiry(),
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


def booking_scenario(
    client: TestClient,
    airports: list[dict[str, Any]],
    *,
    confirm: bool = True,
    operator_amount_minor: int = 1_000_000,
    tax_amount_minor: int = 50_000,
) -> dict[str, Any]:
    """Build customer→operator→aircraft→trip→selected offer→booking.

    The booking is confirmed by default (ready for capture); pass confirm=False to
    keep it PENDING_OPERATOR_CONFIRMATION.
    """
    customer = client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Pay Customer",
            "primary_email": f"pay-{uuid4()}@example.test",
            "preferred_currency": "EUR",
            "timezone": "Europe/Dublin",
        },
    ).json()
    operator = client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Pay Aviation {uuid4()}",
            "country_code": "IE",
            "contact_email": f"ops-{uuid4()}@example.test",
        },
    ).json()
    aircraft = client.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator["id"],
            "manufacturer": "Cessna",
            "model": "Citation CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 7,
        },
    ).json()
    make_operator_eligible(client, operator["id"], aircraft["id"])
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
    offer = client.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip["id"],
            "operator_id": operator["id"],
            "aircraft_id": aircraft["id"],
            "currency": "EUR",
            "operator_amount_minor": operator_amount_minor,
            "tax_amount_minor": tax_amount_minor,
            "valid_until": _future_iso(),
        },
    ).json()
    client.post(f"/api/v1/offers/{offer['id']}/submit")
    client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    booking = client.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    ).json()
    if confirm:
        confirmed = client.post(
            f"/api/v1/bookings/{booking['id']}/confirm", json={"operator_id": operator["id"]}
        )
        assert confirmed.status_code == 200, confirmed.text
        booking = confirmed.json()
    return {
        "customer": customer,
        "operator": operator,
        "trip": trip,
        "offer": offer,
        "booking": booking,
    }


def create_payment(client: TestClient, booking_id: str) -> dict[str, Any]:
    response = client.post(f"/api/v1/bookings/{booking_id}/payment")
    assert response.status_code == 201, response.text
    return response.json()


def authorize(
    client: TestClient, payment_id: str, *, key: str | None = None, method: str | None = None
) -> Any:
    body: dict[str, Any] = {"idempotency_key": key or new_key()}
    if method is not None:
        body["payment_method_reference"] = method
    return client.post(f"/api/v1/payments/{payment_id}/authorize", json=body)


def capture(client: TestClient, payment_id: str, *, key: str | None = None) -> Any:
    return client.post(
        f"/api/v1/payments/{payment_id}/capture", json={"idempotency_key": key or new_key()}
    )


def void(client: TestClient, payment_id: str, *, key: str | None = None) -> Any:
    return client.post(
        f"/api/v1/payments/{payment_id}/void", json={"idempotency_key": key or new_key()}
    )


def refund(
    client: TestClient, payment_id: str, amount_minor: int, *, key: str | None = None
) -> Any:
    return client.post(
        f"/api/v1/payments/{payment_id}/refunds",
        json={"idempotency_key": key or new_key(), "amount_minor": amount_minor},
    )


def authorized_payment(client: TestClient, airports: list[dict[str, Any]], **kwargs: Any) -> dict:
    """Return a scenario whose payment is created and authorized (booking confirmed)."""
    scenario = booking_scenario(client, airports, **kwargs)
    payment = create_payment(client, scenario["booking"]["id"])
    authorized = authorize(client, payment["id"])
    assert authorized.status_code == 200, authorized.text
    scenario["payment"] = authorized.json()
    return scenario
