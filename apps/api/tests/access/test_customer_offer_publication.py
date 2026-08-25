"""Phase 9.4.B0 customer-safe operator-offer publication boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import iam_support
import pytest
from fastapi.testclient import TestClient
from offers._support import (
    create_aircraft,
    create_customer,
    create_operator,
    offer_payload,
    submitted_trip,
)

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.offers.models import OperatorOffer

requires_db = pytest.mark.skipif(
    __import__("os").getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_CONFIDENTIAL_FIELDS = {
    "operator_id",
    "aircraft_id",
    "operator_amount_minor",
    "platform_fee_minor",
    "operator_notes",
}


def _create_offer(
    admin: TestClient,
    *,
    trip_id: str,
    operator_id: str,
    amount: int,
) -> dict[str, Any]:
    aircraft = create_aircraft(admin, operator_id)
    response = admin.post(
        "/api/v1/offers",
        json=offer_payload(
            trip_request_id=trip_id,
            operator_id=operator_id,
            aircraft_id=aircraft["id"],
            operator_amount_minor=amount,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


@requires_db
def test_customer_publication_filters_mixed_lifecycle_and_preserves_internal_visibility(
    admin: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(admin)
    operator = create_operator(admin)
    trip = submitted_trip(admin, customer["id"], airports)

    draft = _create_offer(admin, trip_id=trip["id"], operator_id=operator["id"], amount=1_000_000)
    submitted = _create_offer(
        admin, trip_id=trip["id"], operator_id=operator["id"], amount=2_000_000
    )
    expired = _create_offer(admin, trip_id=trip["id"], operator_id=operator["id"], amount=3_000_000)
    withdrawn = _create_offer(
        admin, trip_id=trip["id"], operator_id=operator["id"], amount=4_000_000
    )
    selected = _create_offer(
        admin, trip_id=trip["id"], operator_id=operator["id"], amount=5_000_000
    )

    for offer in (submitted, expired, selected):
        response = admin.post(f"/api/v1/offers/{offer['id']}/submit")
        assert response.status_code == 200, response.text
    response = admin.post(f"/api/v1/offers/{withdrawn['id']}/withdraw")
    assert response.status_code == 200, response.text
    response = admin.post(f"/api/v1/trip-requests/{trip['id']}/offers/{selected['id']}/select")
    assert response.status_code == 200, response.text

    # Expiration is effective-only: keep the persisted state SUBMITTED and move its
    # validity into the past to model time passing after a valid submission.
    with SessionLocal() as session, session.begin():
        persisted = session.get(OperatorOffer, UUID(expired["id"]))
        assert persisted is not None
        persisted.valid_until = datetime.now(UTC) - timedelta(minutes=1)

    customer_client, _ = iam_support.customer_owner_client(admin, UUID(customer["id"]))
    response = customer_client.get(f"/api/v1/trip-requests/{trip['id']}/offers")
    assert response.status_code == 200, response.text
    customer_rows = {row["id"]: row for row in response.json()}

    assert set(customer_rows) == {submitted["id"], expired["id"], selected["id"]}
    assert draft["id"] not in customer_rows
    assert withdrawn["id"] not in customer_rows
    assert customer_rows[submitted["id"]]["status"] == "SUBMITTED"
    assert customer_rows[expired["id"]]["status"] == "EXPIRED"
    assert customer_rows[selected["id"]]["status"] == "SELECTED"
    assert all(row["response_audience"] == "customer" for row in customer_rows.values())
    assert all(_CONFIDENTIAL_FIELDS.isdisjoint(row) for row in customer_rows.values())

    # The same authorized platform route retains complete lifecycle observability.
    internal = admin.get(f"/api/v1/trip-requests/{trip['id']}/offers")
    assert internal.status_code == 200, internal.text
    internal_rows = {row["id"]: row for row in internal.json()}
    assert set(internal_rows) == {
        draft["id"],
        submitted["id"],
        expired["id"],
        withdrawn["id"],
        selected["id"],
    }
    assert internal_rows[draft["id"]]["status"] == "DRAFT"
    assert internal_rows[submitted["id"]]["status"] == "SUBMITTED"
    assert internal_rows[expired["id"]]["status"] == "EXPIRED"
    assert internal_rows[withdrawn["id"]]["status"] == "WITHDRAWN"
    assert internal_rows[selected["id"]]["status"] == "SELECTED"
    assert all(row["response_audience"] == "internal" for row in internal_rows.values())
    assert all("operator_amount_minor" in row for row in internal_rows.values())

    other, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    concealed = other.get(f"/api/v1/trip-requests/{trip['id']}/offers")
    assert concealed.status_code == 404
