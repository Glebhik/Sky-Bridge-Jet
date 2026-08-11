from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from ._support import (
    booking_scenario,
    create_aircraft,
    create_booking,
    create_customer,
    create_operator,
    draft_offer,
    requires_db,
    submitted_trip,
)

pytestmark = requires_db


def test_create_booking_from_selected_offer_snapshots_commercials(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(
        client, airports, operator_amount_minor=1_000_000, tax_amount_minor=50_000
    )
    response = create_booking(client, scenario)
    assert response.status_code == 201, response.text
    booking = response.json()

    assert booking["status"] == "PENDING_OPERATOR_CONFIRMATION"
    assert booking["reference"].startswith("SBJ-")
    assert booking["operator_offer_id"] == scenario["offer"]["id"]
    assert booking["operator_id"] == scenario["operator"]["id"]
    # Commercial snapshot copied exactly from the selected offer.
    offer = scenario["offer"]
    for field in (
        "currency",
        "operator_amount_minor",
        "platform_fee_minor",
        "tax_amount_minor",
        "total_amount_minor",
        "operator_legal_name",
        "aircraft_registration",
        "aircraft_category",
    ):
        assert booking[field] == offer[field]
    assert booking["total_amount_minor"] == 1_140_000


def test_create_booking_rejected_for_draft_offer(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    trip = submitted_trip(client, customer["id"], airports)
    offer = draft_offer(
        client,
        trip_request_id=trip["id"],
        operator_id=operator["id"],
        aircraft_id=aircraft["id"],
    )
    response = client.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_allowed"


def test_create_booking_rejected_for_submitted_not_selected_offer(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    trip = submitted_trip(client, customer["id"], airports)
    offer = draft_offer(
        client,
        trip_request_id=trip["id"],
        operator_id=operator["id"],
        aircraft_id=aircraft["id"],
    )
    assert client.post(f"/api/v1/offers/{offer['id']}/submit").status_code == 200

    response = client.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_allowed"


def test_create_booking_rejected_for_cancelled_trip(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    trip = scenario["trip"]
    cancelled = client.post(
        f"/api/v1/trip-requests/{trip['id']}/cancel",
        json={"expected_version": trip["version"]},
    )
    assert cancelled.status_code == 200
    response = create_booking(client, scenario)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_allowed"


def test_create_booking_rejects_offer_of_another_trip(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario_a = booking_scenario(client, airports)
    scenario_b = booking_scenario(client, airports)
    response = client.post(
        "/api/v1/bookings",
        json={
            "trip_request_id": scenario_a["trip"]["id"],
            "operator_offer_id": scenario_b["offer"]["id"],
        },
    )
    assert response.status_code == 404


def test_one_active_booking_invariant_and_repeated_creation(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    first = create_booking(client, scenario)
    assert first.status_code == 201
    # Repeated creation for the same selected offer does not create a duplicate.
    second = create_booking(client, scenario)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "booking_not_allowed"


def test_booking_references_are_unique(client: TestClient, airports: list[dict[str, Any]]) -> None:
    refs = set()
    for _ in range(4):
        booking = create_booking(client, booking_scenario(client, airports)).json()
        refs.add(booking["reference"])
    assert len(refs) == 4


def test_get_booking_and_get_for_trip(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()

    fetched = client.get(f"/api/v1/bookings/{booking['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == booking["id"]

    for_trip = client.get(f"/api/v1/trip-requests/{scenario['trip']['id']}/booking")
    assert for_trip.status_code == 200
    assert for_trip.json()["id"] == booking["id"]


def test_get_missing_booking_returns_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/bookings/{uuid4()}").status_code == 404


def test_operator_confirms_booking(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()

    confirmed = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={
            "operator_id": scenario["operator"]["id"],
            "confirmation_reference": "OP-REF-123",
            "note": "Crew and slot confirmed",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "CONFIRMED"
    assert body["confirmed_at"] is not None
    assert body["operator_confirmation_reference"] == "OP-REF-123"


def test_confirm_rejects_wrong_operator(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    other_operator = create_operator(client)

    response = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={"operator_id": other_operator["id"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "operator_mismatch"


def test_repeated_confirmation_is_a_deterministic_conflict(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    operator_id = scenario["operator"]["id"]
    first = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm", json={"operator_id": operator_id}
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm", json={"operator_id": operator_id}
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_booking_state"


def test_operator_rejects_booking_with_structured_reason(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()

    rejected = client.post(
        f"/api/v1/bookings/{booking['id']}/reject",
        json={
            "operator_id": scenario["operator"]["id"],
            "reason": "AIRCRAFT_UNAVAILABLE",
            "note": "Aircraft in maintenance",
        },
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == "REJECTED"
    assert body["rejection_reason"] == "AIRCRAFT_UNAVAILABLE"
    assert body["rejected_at"] is not None

    # A rejected booking cannot be confirmed.
    confirm = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert confirm.status_code == 409
    assert confirm.json()["error"]["code"] == "invalid_booking_state"


def test_reject_requires_valid_reason(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    response = client.post(
        f"/api/v1/bookings/{booking['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "NOT_A_REASON"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_cancel_pending_and_confirmed_bookings(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    # Cancel a pending booking.
    scenario = booking_scenario(client, airports)
    pending = create_booking(client, scenario).json()
    cancelled = client.post(
        f"/api/v1/bookings/{pending['id']}/cancel",
        json={"actor": "CUSTOMER", "reason": "NO_LONGER_REQUIRED"},
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "CANCELLED"
    assert body["cancellation_actor"] == "CUSTOMER"

    # Cancel a confirmed booking.
    scenario2 = booking_scenario(client, airports)
    booking2 = create_booking(client, scenario2).json()
    client.post(
        f"/api/v1/bookings/{booking2['id']}/confirm",
        json={"operator_id": scenario2["operator"]["id"]},
    )
    cancelled2 = client.post(
        f"/api/v1/bookings/{booking2['id']}/cancel", json={"actor": "OPERATOR"}
    )
    assert cancelled2.status_code == 200
    assert cancelled2.json()["status"] == "CANCELLED"


def test_cancelled_booking_cannot_be_confirmed(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    client.post(f"/api/v1/bookings/{booking['id']}/cancel", json={"actor": "PLATFORM"})
    response = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_booking_state"


def test_new_booking_allowed_after_rejection(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    client.post(
        f"/api/v1/bookings/{booking['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "OTHER"},
    )
    # The selected offer remains, so a fresh booking workflow is allowed.
    again = create_booking(client, scenario)
    assert again.status_code == 201
    assert again.json()["id"] != booking["id"]


def test_commercial_snapshot_immutable_across_lifecycle(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    created = create_booking(client, scenario).json()
    snapshot = {k: created[k] for k in ("currency", "operator_amount_minor", "total_amount_minor")}

    client.post(
        f"/api/v1/bookings/{created['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    after = client.get(f"/api/v1/bookings/{created['id']}").json()
    assert {k: after[k] for k in snapshot} == snapshot
