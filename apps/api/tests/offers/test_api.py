from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from ._support import (
    create_aircraft,
    create_customer,
    create_operator,
    future_iso,
    offer_payload,
    requires_db,
    submitted_trip,
)

pytestmark = requires_db


def _new_offer(client: TestClient, airports: list[dict[str, Any]], **overrides: Any) -> dict:
    customer = create_customer(client)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    trip = submitted_trip(client, customer["id"], airports)
    payload = offer_payload(
        trip_request_id=trip["id"],
        operator_id=operator["id"],
        aircraft_id=aircraft["id"],
        **overrides,
    )
    response = client.post("/api/v1/offers", json=payload)
    return {
        "response": response,
        "customer": customer,
        "operator": operator,
        "aircraft": aircraft,
        "trip": trip,
    }


def test_create_offer_computes_fee_and_total_and_snapshots(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    context = _new_offer(client, airports, operator_amount_minor=1_000_000, tax_amount_minor=50_000)
    response = context["response"]
    assert response.status_code == 201, response.text
    offer = response.json()

    assert offer["status"] == "DRAFT"
    assert offer["currency"] == "EUR"
    assert offer["operator_amount_minor"] == 1_000_000
    assert offer["platform_fee_minor"] == 90_000  # 9% derived platform fee
    assert offer["tax_amount_minor"] == 50_000
    assert offer["total_amount_minor"] == 1_140_000
    # Historical snapshots captured from operator and aircraft.
    assert offer["operator_legal_name"] == context["operator"]["legal_name"]
    assert offer["aircraft_registration"] == context["aircraft"]["registration"]
    assert offer["aircraft_category"] == "LIGHT_JET"

    fetched = client.get(f"/api/v1/offers/{offer['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == offer["id"]


def test_create_offer_rejects_unsupported_currency(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    result = _new_offer(client, airports, currency="JPY")
    assert result["response"].status_code == 422
    body = result["response"].json()
    assert body["error"]["code"] == "validation_error"
    assert "input" not in str(body)


def test_create_offer_rejects_negative_amount(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    result = _new_offer(client, airports, operator_amount_minor=-1)
    assert result["response"].status_code == 422
    assert result["response"].json()["error"]["code"] == "validation_error"


def test_create_offer_rejects_aircraft_of_another_operator(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator_a = create_operator(client)
    operator_b = create_operator(client)
    aircraft_b = create_aircraft(client, operator_b["id"])
    trip = submitted_trip(client, customer["id"], airports)

    response = client.post(
        "/api/v1/offers",
        json=offer_payload(
            trip_request_id=trip["id"],
            operator_id=operator_a["id"],
            aircraft_id=aircraft_b["id"],
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "domain_validation_error"


def test_create_offer_rejected_for_draft_trip(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    draft_trip = client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer["id"],
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

    response = client.post(
        "/api/v1/offers",
        json=offer_payload(
            trip_request_id=draft_trip["id"],
            operator_id=operator["id"],
            aircraft_id=aircraft["id"],
        ),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "trip_not_accepting_offers"


def test_create_offer_rejected_for_missing_trip(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    response = client.post(
        "/api/v1/offers",
        json=offer_payload(
            trip_request_id="00000000-0000-0000-0000-000000000000",
            operator_id=operator["id"],
            aircraft_id=aircraft["id"],
        ),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"


def test_draft_update_recomputes_fee_then_freezes_on_submit(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    offer = _new_offer(client, airports)["response"].json()

    updated = client.patch(
        f"/api/v1/offers/{offer['id']}",
        json={"operator_amount_minor": 2_000_000, "operator_notes": "Includes de-icing"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["operator_amount_minor"] == 2_000_000
    assert body["platform_fee_minor"] == 180_000
    assert body["total_amount_minor"] == 2_180_000
    assert body["operator_notes"] == "Includes de-icing"

    submitted = client.post(f"/api/v1/offers/{offer['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "SUBMITTED"

    # Commercial terms are frozen once submitted.
    frozen = client.patch(f"/api/v1/offers/{offer['id']}", json={"operator_amount_minor": 1})
    assert frozen.status_code == 409
    assert frozen.json()["error"]["code"] == "invalid_offer_state"


def test_submit_requires_future_validity(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    # Missing validity is rejected.
    offer = _new_offer(client, airports, valid_until=None)["response"].json()
    missing = client.post(f"/api/v1/offers/{offer['id']}/submit")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "domain_validation_error"

    # Past validity is rejected.
    client.patch(f"/api/v1/offers/{offer['id']}", json={"valid_until": "2020-01-01T00:00:00+00:00"})
    past = client.post(f"/api/v1/offers/{offer['id']}/submit")
    assert past.status_code == 422

    # Future validity submits.
    client.patch(f"/api/v1/offers/{offer['id']}", json={"valid_until": future_iso()})
    ok = client.post(f"/api/v1/offers/{offer['id']}/submit")
    assert ok.status_code == 200
    assert ok.json()["status"] == "SUBMITTED"


def test_withdraw_offer_blocks_further_transitions(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    offer = _new_offer(client, airports)["response"].json()
    client.post(f"/api/v1/offers/{offer['id']}/submit")

    withdrawn = client.post(f"/api/v1/offers/{offer['id']}/withdraw")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"

    again = client.post(f"/api/v1/offers/{offer['id']}/withdraw")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_offer_state"


def test_duplicate_active_offer_for_same_aircraft_rejected(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    context = _new_offer(client, airports)
    trip, operator, aircraft = context["trip"], context["operator"], context["aircraft"]
    assert context["response"].status_code == 201

    duplicate = client.post(
        "/api/v1/offers",
        json=offer_payload(
            trip_request_id=trip["id"],
            operator_id=operator["id"],
            aircraft_id=aircraft["id"],
        ),
    )
    assert duplicate.status_code == 409


def test_list_offers_for_trip_is_price_ordered(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    trip = submitted_trip(client, customer["id"], airports)

    amounts = [3_000_000, 1_000_000, 2_000_000]
    for amount in amounts:
        aircraft = create_aircraft(client, operator["id"])
        created = client.post(
            "/api/v1/offers",
            json=offer_payload(
                trip_request_id=trip["id"],
                operator_id=operator["id"],
                aircraft_id=aircraft["id"],
                operator_amount_minor=amount,
            ),
        )
        assert created.status_code == 201, created.text

    listed = client.get(f"/api/v1/trip-requests/{trip['id']}/offers")
    assert listed.status_code == 200
    totals = [offer["total_amount_minor"] for offer in listed.json()]
    assert totals == sorted(totals)
    assert len(totals) == 3


def test_list_offers_for_missing_trip_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/trip-requests/00000000-0000-0000-0000-000000000000/offers")
    assert response.status_code == 404
