"""M1/M2 — complete cross-tenant coverage for every customer-chain bound route.

Uses real, distinct CUSTOMER principals (never PRODUCT_OWNER). For each previously
uncovered route it proves Customer A cannot reach Customer B's resource (404
concealment) and that no state changed; M2 mirrors representative paths B→A.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.models import Booking

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _draft_trip(client: TestClient, customer_id: str, airports: list) -> dict:
    return client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer_id,
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


def _submitted_trip(client: TestClient, customer_id: str, airports: list) -> dict:
    trip = _draft_trip(client, customer_id, airports)
    client.post(
        f"/api/v1/trip-requests/{trip['id']}/submit", json={"expected_version": trip["version"]}
    )
    return trip


def _trip_status(admin: TestClient, trip_id: str) -> str:
    return str(admin.get(f"/api/v1/trip-requests/{trip_id}").json()["status"])


def _booking_status(admin: TestClient, booking_id: str) -> str:
    return str(admin.get(f"/api/v1/bookings/{booking_id}").json()["status"])


def _count_bookings_for_trip(trip_id: str) -> int:
    with SessionLocal() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(Booking)
                .where(Booking.trip_request_id == UUID(trip_id))
            )
            or 0
        )


# --------------------------------------------------------------------------- #
# M1 — the six previously uncovered routes (A → B)
# --------------------------------------------------------------------------- #
@requires_db
def test_a_cannot_cancel_b_trip(admin: TestClient, airports: list) -> None:
    b_id = iam_support.create_customer(admin)
    b_client, _ = iam_support.customer_owner_client(admin, b_id)
    a_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    b_trip = _draft_trip(b_client, str(b_id), airports)

    denied = a_client.post(
        f"/api/v1/trip-requests/{b_trip['id']}/cancel", json={"expected_version": b_trip["version"]}
    )
    assert denied.status_code == 404
    assert _trip_status(admin, b_trip["id"]) == "DRAFT"  # no lifecycle mutation


@requires_db
def test_a_cannot_select_offers(admin: TestClient, airports: list) -> None:
    b = iam_support.full_booking_scenario(admin, airports, confirm=False)
    a_id = iam_support.create_customer(admin)
    a_client, _ = iam_support.customer_owner_client(admin, a_id)

    # A cannot select an offer on B's trip (does not own the trip).
    on_b_trip = a_client.post(f"/api/v1/trip-requests/{b['trip_id']}/offers/{b['offer_id']}/select")
    assert on_b_trip.status_code == 404

    # A cannot select B's offer against A's own trip (offer does not belong to it).
    a_trip = _submitted_trip(a_client, str(a_id), airports)
    foreign = a_client.post(f"/api/v1/trip-requests/{a_trip['id']}/offers/{b['offer_id']}/select")
    assert foreign.status_code == 404
    # A's trip retains no selected offer (its own offers are empty → still SUBMITTED).
    assert _trip_status(admin, a_trip["id"]) == "SUBMITTED"


@requires_db
def test_a_cannot_create_booking_from_b_offer(admin: TestClient, airports: list) -> None:
    b = iam_support.full_booking_scenario(admin, airports, confirm=False)
    a_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    before = _count_bookings_for_trip(b["trip_id"])

    denied = a_client.post(
        "/api/v1/bookings",
        json={"trip_request_id": b["trip_id"], "operator_offer_id": b["offer_id"]},
    )
    assert denied.status_code == 404
    assert _count_bookings_for_trip(b["trip_id"]) == before  # no booking created


@requires_db
def test_a_cannot_cancel_b_booking(admin: TestClient, airports: list) -> None:
    b = iam_support.full_booking_scenario(admin, airports)
    a_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))

    denied = a_client.post(f"/api/v1/bookings/{b['booking_id']}/cancel", json={"actor": "CUSTOMER"})
    assert denied.status_code == 404
    assert _booking_status(admin, b["booking_id"]) == "CONFIRMED"  # unchanged


@requires_db
def test_a_cannot_read_b_booking_via_trip(admin: TestClient, airports: list) -> None:
    b = iam_support.full_booking_scenario(admin, airports)
    a_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    denied = a_client.get(f"/api/v1/trip-requests/{b['trip_id']}/booking")
    assert denied.status_code == 404
    assert "platform_fee_minor" not in denied.text
    assert "operator_amount_minor" not in denied.text


@requires_db
def test_a_cannot_read_b_payment_via_booking(admin: TestClient, airports: list) -> None:
    b = iam_support.full_booking_scenario(admin, airports)
    a_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    denied = a_client.get(f"/api/v1/bookings/{b['booking_id']}/payment")
    assert denied.status_code == 404
    assert "platform_fee_minor" not in denied.text
    assert "operator_amount_minor" not in denied.text


# --------------------------------------------------------------------------- #
# M2 — symmetric isolation (B → A): read, mutation, confidential path
# --------------------------------------------------------------------------- #
@requires_db
def test_symmetric_b_cannot_access_a(admin: TestClient, airports: list) -> None:
    a = iam_support.full_booking_scenario(admin, airports)
    a_customer = a["customer_id"]
    a_client, _ = iam_support.customer_owner_client(admin, UUID(a_customer))
    b_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))

    # Direct object read (B → A customer record).
    assert b_client.get(f"/api/v1/customers/{a_customer}").status_code == 404
    # Lifecycle mutation (B cancels A's booking).
    assert (
        b_client.post(
            f"/api/v1/bookings/{a['booking_id']}/cancel", json={"actor": "CUSTOMER"}
        ).status_code
        == 404
    )
    assert _booking_status(admin, a["booking_id"]) == "CONFIRMED"
    # Confidential dual-owned path (B reads A's payment).
    confidential = b_client.get(f"/api/v1/payments/{a['payment_id']}")
    assert confidential.status_code == 404
    assert "platform_fee_minor" not in confidential.text

    # And the owning customer A is (temporarily) 403 on the confidential path, proving
    # the 403-vs-404 distinction is by tenant, not by resource existence.
    assert a_client.get(f"/api/v1/payments/{a['payment_id']}").status_code == 403
    assert a_client.get(f"/api/v1/customers/{uuid4()}").status_code == 404
