from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import iam_support
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.iam.models import Organization
from sky_bridge_jet.modules.payments.models import Payment

from ._support import (
    booking_scenario,
    create_booking,
    requires_db,
    selected_offer,
    submitted_trip,
)

pytestmark = requires_db


def _operator_client(scenario: dict[str, Any], role: OrganizationRole) -> tuple[TestClient, str]:
    operator_id = UUID(scenario["operator"]["id"])
    with SessionLocal() as session:
        organization_id = session.query(Organization.id).filter_by(operator_id=operator_id).scalar()
    if organization_id is None:
        client, organization_id = iam_support.operator_role_client(operator_id, role)
    else:
        client = iam_support.member_client_for_org(organization_id, role)
    client.headers["X-Organization-Id"] = str(organization_id)
    return client, str(organization_id)


def test_operator_queue_is_tenant_scoped_minimal_and_deterministic(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    own = booking_scenario(client, airports)
    first = create_booking(client, own).json()
    foreign = booking_scenario(client, airports)
    foreign_booking = create_booking(client, foreign).json()

    operator, _ = _operator_client(own, OrganizationRole.OPERATOR_ADMIN)
    response = operator.get("/api/v1/me/operator-bookings?limit=50&offset=0")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["booking_id"] for item in body] == [first["id"]]
    assert foreign_booking["id"] not in {item["booking_id"] for item in body}
    item = body[0]
    assert item["legs"][0]["origin_airport_code"]
    assert item["legs"][0]["passenger_count"] == 2
    assert item["operator_amount_minor"] == first["operator_amount_minor"]
    forbidden = {
        "customer_id",
        "customer_email",
        "customer_phone",
        "platform_fee_minor",
        "total_amount_minor",
        "tax_amount_minor",
        "payment",
        "provider_id",
        "confirmation_note",
        "rejection_note",
    }
    assert forbidden.isdisjoint(item)
    operator.close()


def test_operator_queue_role_and_context_policy(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    create_booking(client, scenario)
    for role in (
        OrganizationRole.OPERATOR_ADMIN,
        OrganizationRole.OPERATOR_OPERATIONS,
        OrganizationRole.OPERATOR_SALES,
    ):
        actor, _ = _operator_client(scenario, role)
        assert actor.get("/api/v1/me/operator-bookings").status_code == 200
        assert actor.get("/api/v1/me/operator-bookings?limit=0").status_code == 422
        actor.close()

    customer_actor = iam_support.new_client()
    iam_support.register_verify_login(customer_actor)
    assert customer_actor.get("/api/v1/me/operator-bookings").status_code == 403
    customer_actor.headers["X-Organization-Id"] = str(uuid4())
    assert customer_actor.get("/api/v1/me/operator-bookings").status_code == 403
    customer_actor.close()


def test_operator_queue_orders_and_paginates_before_tenant_materialization(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    own = booking_scenario(client, airports)
    bookings: list[dict[str, Any]] = []
    for _ in range(3):
        trip = submitted_trip(client, own["customer"]["id"], airports)
        offer = selected_offer(
            client,
            trip_request_id=trip["id"],
            operator_id=own["operator"]["id"],
            aircraft_id=own["aircraft"]["id"],
        )
        bookings.append(create_booking(client, {"trip": trip, "offer": offer}).json())
    foreign = create_booking(client, booking_scenario(client, airports)).json()

    tied_created_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    with SessionLocal() as session:
        for booking in bookings:
            session.get(Booking, UUID(booking["id"])).created_at = tied_created_at
        session.commit()

    expected = sorted(booking["id"] for booking in bookings)
    operator, _ = _operator_client(own, OrganizationRole.OPERATOR_ADMIN)
    first = operator.get("/api/v1/me/operator-bookings?limit=2&offset=0")
    second = operator.get("/api/v1/me/operator-bookings?limit=2&offset=2")
    assert first.status_code == 200
    assert second.status_code == 200
    assert [item["booking_id"] for item in first.json()] == expected[:2]
    assert [item["booking_id"] for item in second.json()] == expected[2:]
    assert foreign["id"] not in {item["booking_id"] for item in first.json() + second.json()}
    assert operator.get("/api/v1/me/operator-bookings?limit=1").status_code == 200
    assert operator.get("/api/v1/me/operator-bookings?limit=100").status_code == 200
    assert operator.get("/api/v1/me/operator-bookings?limit=101").status_code == 422
    assert operator.get("/api/v1/me/operator-bookings?offset=-1").status_code == 422
    operator.close()


def test_operator_decision_derives_identity_and_removes_item_from_queue(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    operator, _ = _operator_client(scenario, OrganizationRole.OPERATOR_OPERATIONS)
    with SessionLocal() as session:
        payment_count_before = session.query(Payment).count()

    confirmed = operator.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={"confirmation_reference": "OPS-95B"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"
    assert operator.get("/api/v1/me/operator-bookings").json() == []
    second = operator.post(f"/api/v1/bookings/{booking['id']}/confirm", json={})
    assert second.status_code == 409
    with SessionLocal() as session:
        assert session.query(Payment).count() == payment_count_before
    operator.close()


def test_decision_compatibility_wrong_tenant_and_read_only_role(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking = create_booking(client, scenario).json()
    admin, _ = _operator_client(scenario, OrganizationRole.OPERATOR_ADMIN)
    mismatch = admin.post(
        f"/api/v1/bookings/{booking['id']}/reject",
        json={"operator_id": str(uuid4()), "reason": "OTHER"},
    )
    assert mismatch.status_code == 409
    admin.close()

    sales, _ = _operator_client(scenario, OrganizationRole.OPERATOR_SALES)
    assert sales.get("/api/v1/me/operator-bookings").status_code == 200
    denied = sales.post(f"/api/v1/bookings/{booking['id']}/reject", json={"reason": "OTHER"})
    assert denied.status_code == 403
    sales.close()

    foreign = booking_scenario(client, airports)
    foreign_actor, _ = _operator_client(foreign, OrganizationRole.OPERATOR_ADMIN)
    hidden = foreign_actor.post(
        f"/api/v1/bookings/{booking['id']}/reject", json={"reason": "OTHER"}
    )
    assert hidden.status_code == 404
    foreign_actor.close()
