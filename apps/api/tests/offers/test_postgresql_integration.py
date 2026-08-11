from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.offers.domain import OfferNotSelectableError, OfferStatus
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.offers.services import OperatorOfferService

from ._support import (
    create_aircraft,
    create_customer,
    create_operator,
    offer_payload,
    requires_db,
    submitted_trip,
)

pytestmark = requires_db


def _submitted_offer(
    client: TestClient, airports: list[dict[str, Any]], trip: dict | None = None, operator=None
) -> tuple[dict, dict]:
    """Create and submit an offer, returning (offer, trip)."""
    if operator is None:
        operator = create_operator(client)
    if trip is None:
        customer = create_customer(client)
        trip = submitted_trip(client, customer["id"], airports)
    aircraft = create_aircraft(client, operator["id"])
    offer = client.post(
        "/api/v1/offers",
        json=offer_payload(
            trip_request_id=trip["id"],
            operator_id=operator["id"],
            aircraft_id=aircraft["id"],
        ),
    ).json()
    submitted = client.post(f"/api/v1/offers/{offer['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    return submitted.json(), trip


def test_select_offer_happy_path(client: TestClient, airports: list[dict[str, Any]]) -> None:
    offer, trip = _submitted_offer(client, airports)
    response = client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SELECTED"


def test_select_rejects_cross_trip_offer(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    offer, _ = _submitted_offer(client, airports)
    other_customer = create_customer(client)
    other_trip = submitted_trip(client, other_customer["id"], airports)
    response = client.post(f"/api/v1/trip-requests/{other_trip['id']}/offers/{offer['id']}/select")
    assert response.status_code == 404


def test_select_rejects_withdrawn_offer(client: TestClient, airports: list[dict[str, Any]]) -> None:
    offer, trip = _submitted_offer(client, airports)
    client.post(f"/api/v1/offers/{offer['id']}/withdraw")
    response = client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "offer_not_selectable"


def test_select_rejects_expired_offer(client: TestClient, airports: list[dict[str, Any]]) -> None:
    offer, trip = _submitted_offer(client, airports)
    # Simulate the validity window elapsing after a valid submission.
    with SessionLocal() as session, session.begin():
        persisted = session.get(OperatorOffer, UUID(offer["id"]))
        assert persisted is not None
        persisted.valid_until = datetime.now(UTC) - timedelta(minutes=1)

    fetched = client.get(f"/api/v1/offers/{offer['id']}")
    assert fetched.json()["status"] == "EXPIRED"

    response = client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "offer_not_selectable"


def test_select_rejects_cancelled_trip(client: TestClient, airports: list[dict[str, Any]]) -> None:
    offer, trip = _submitted_offer(client, airports)
    cancelled = client.post(
        f"/api/v1/trip-requests/{trip['id']}/cancel", json={"expected_version": trip["version"]}
    )
    assert cancelled.status_code == 200
    response = client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "trip_not_accepting_offers"


def test_single_selection_second_offer_rejected(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    trip = submitted_trip(client, customer["id"], airports)
    offer_one, _ = _submitted_offer(client, airports, trip=trip, operator=operator)
    offer_two, _ = _submitted_offer(client, airports, trip=trip, operator=operator)

    first = client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer_one['id']}/select")
    assert first.status_code == 200
    second = client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer_two['id']}/select")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "offer_not_selectable"


def test_concurrent_selection_yields_exactly_one_selected(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    trip = submitted_trip(client, customer["id"], airports)
    offer_one, _ = _submitted_offer(client, airports, trip=trip, operator=operator)
    offer_two, _ = _submitted_offer(client, airports, trip=trip, operator=operator)
    trip_id = UUID(trip["id"])

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(offer_id: str) -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                OperatorOfferService(session).select(trip_id, UUID(offer_id))
            result = "selected"
        except (OfferNotSelectableError, IntegrityError):
            result = "rejected"
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=attempt, args=(offer_one["id"],)),
        threading.Thread(target=attempt, args=(offer_two["id"],)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["rejected", "selected"]
    with SessionLocal() as session:
        selected = (
            session.query(OperatorOffer)
            .filter(
                OperatorOffer.trip_request_id == trip_id,
                OperatorOffer.status == OfferStatus.SELECTED,
            )
            .count()
        )
    assert selected == 1


# -- Database-level invariants, bypassing the service layer ------------------


def _prerequisites(client: TestClient, airports: list[dict[str, Any]]) -> dict[str, Any]:
    customer = create_customer(client)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    trip = submitted_trip(client, customer["id"], airports)
    return {"operator": operator, "aircraft": aircraft, "trip": trip}


def _raw_offer(prereq: dict[str, Any], **overrides: Any) -> OperatorOffer:
    defaults: dict[str, Any] = {
        "trip_request_id": UUID(prereq["trip"]["id"]),
        "operator_id": UUID(prereq["operator"]["id"]),
        "aircraft_id": UUID(prereq["aircraft"]["id"]),
        "status": OfferStatus.DRAFT,
        "currency": "EUR",
        "operator_amount_minor": 1_000_000,
        "platform_fee_minor": 90_000,
        "tax_amount_minor": 0,
        "total_amount_minor": 1_090_000,
        "valid_until": datetime.now(UTC) + timedelta(days=1),
        "operator_legal_name": prereq["operator"]["legal_name"],
        "aircraft_registration": prereq["aircraft"]["registration"],
        "aircraft_manufacturer": "Cessna",
        "aircraft_model": "Citation CJ3+",
        "aircraft_category": "LIGHT_JET",
    }
    defaults.update(overrides)
    return OperatorOffer(**defaults)


def test_db_rejects_price_inconsistency(client: TestClient, airports: list[dict[str, Any]]) -> None:
    prereq = _prerequisites(client, airports)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_offer(prereq, total_amount_minor=999))  # not operator+fee+tax
        session.commit()


def test_db_rejects_negative_amount(client: TestClient, airports: list[dict[str, Any]]) -> None:
    prereq = _prerequisites(client, airports)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            _raw_offer(
                prereq,
                operator_amount_minor=-1,
                platform_fee_minor=0,
                tax_amount_minor=0,
                total_amount_minor=-1,
            )
        )
        session.commit()


def test_db_rejects_aircraft_of_another_operator(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    prereq = _prerequisites(client, airports)
    other_operator = create_operator(client)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        # Aircraft belongs to prereq["operator"], not other_operator.
        session.add(_raw_offer(prereq, operator_id=UUID(other_operator["id"])))
        session.commit()


def test_db_rejects_second_selected_offer_for_trip(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    operator = create_operator(client)
    trip = submitted_trip(client, customer["id"], airports)
    aircraft_one = create_aircraft(client, operator["id"])
    aircraft_two = create_aircraft(client, operator["id"])
    prereq_one = {"operator": operator, "aircraft": aircraft_one, "trip": trip}
    prereq_two = {"operator": operator, "aircraft": aircraft_two, "trip": trip}

    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_offer(prereq_one, status=OfferStatus.SELECTED))
        session.add(_raw_offer(prereq_two, status=OfferStatus.SELECTED))
        session.commit()
