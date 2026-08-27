from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from sky_bridge_jet.db.session import SessionLocal, engine
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.services import BookingService
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.core_aviation.domain import TripRequestStatus
from sky_bridge_jet.modules.core_aviation.models import Aircraft, TripRequest
from sky_bridge_jet.modules.financials.models import ProviderWebhookEvent
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership
from sky_bridge_jet.modules.iam.router import _register_limiter
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation

from ._support import (
    booking_scenario,
    create_booking,
    selected_offer,
    submitted_trip,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_ROLES = (
    OrganizationRole.OPERATOR_ADMIN,
    OrganizationRole.OPERATOR_SALES,
    OrganizationRole.OPERATOR_OPERATIONS,
    OrganizationRole.OPERATOR_FINANCE,
    OrganizationRole.OPERATOR_COMPLIANCE,
)


def _mutable_domain_counts() -> tuple[int, ...]:
    with SessionLocal() as session:
        return tuple(
            session.query(model).count()
            for model in (
                Aircraft,
                OperatorOffer,
                TripRequest,
                Booking,
                Payment,
                PaymentOperation,
                OperatorAdmission,
                OperatorAircraftAuthorization,
                ComplianceEvidence,
                ComplianceAuditEvent,
                ProviderWebhookEvent,
            )
        )


_SAFE_FIELDS = {
    "id",
    "reference",
    "status",
    "trip_request_id",
    "operator_offer_id",
    "aircraft_id",
    "currency",
    "operator_amount_minor",
    "operator_legal_name",
    "aircraft_registration",
    "aircraft_manufacturer",
    "aircraft_model",
    "aircraft_category",
    "legs",
    "confirmed_at",
    "rejected_at",
    "cancelled_at",
    "created_at",
    "updated_at",
}
_FORBIDDEN = {
    "customer_id",
    "customer_name",
    "customer_email",
    "customer_phone",
    "passengers",
    "date_of_birth",
    "nationality",
    "passport",
    "private_notes",
    "rejection_reason",
    "rejection_note",
    "confirmation_note",
    "cancellation_note",
    "platform_fee_minor",
    "tax_amount_minor",
    "total_amount_minor",
    "payment",
    "payment_operations",
    "provider_kind",
    "provider_reference",
    "provider_status",
    "idempotency_key",
}


@pytest.fixture(autouse=True)
def _keep_later_opportunity_tests_below_their_bounded_page() -> Any:
    with SessionLocal() as session:
        existing_ids = {item[0] for item in session.query(TripRequest.id).all()}
    yield
    with SessionLocal() as session, session.begin():
        session.query(TripRequest).filter(TripRequest.id.not_in(existing_ids)).update(
            {TripRequest.status: TripRequestStatus.CANCELLED},
            synchronize_session=False,
        )


def _organization_id(operator_id: str) -> UUID | None:
    with SessionLocal() as session:
        organization_id = (
            session.query(Organization.id).filter_by(operator_id=UUID(operator_id)).scalar()
        )
    return organization_id


def _actor(operator_id: str, role: OrganizationRole) -> TestClient:
    _register_limiter.clear()
    organization_id = _organization_id(operator_id)
    if organization_id is None:
        actor, organization_id = iam_support.operator_role_client(UUID(operator_id), role)
    else:
        actor = iam_support.member_client_for_org(organization_id, role)
    actor.headers["X-Organization-Id"] = str(organization_id)
    return actor


def _additional_booking(
    client: TestClient, scenario: dict[str, Any], airports: list[dict[str, Any]]
) -> dict[str, Any]:
    trip = submitted_trip(client, scenario["customer"]["id"], airports)
    offer = selected_offer(
        client,
        trip_request_id=trip["id"],
        operator_id=scenario["operator"]["id"],
        aircraft_id=scenario["aircraft"]["id"],
    )
    return create_booking(client, {"trip": trip, "offer": offer}).json()


def _four_states(
    client: TestClient, airports: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenario = booking_scenario(client, airports)
    bookings = [create_booking(client, scenario).json()]
    bookings.extend(_additional_booking(client, scenario, airports) for _ in range(3))
    operator = _actor(scenario["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    assert (
        operator.post(f"/api/v1/bookings/{bookings[1]['id']}/confirm", json={}).status_code == 200
    )
    assert (
        operator.post(
            f"/api/v1/bookings/{bookings[2]['id']}/reject",
            json={"reason": "OTHER", "note": "private rejection note"},
        ).status_code
        == 200
    )
    assert (
        operator.post(
            f"/api/v1/bookings/{bookings[3]['id']}/cancel",
            json={"actor": "OPERATOR", "note": "private cancellation note"},
        ).status_code
        == 200
    )
    operator.close()
    return scenario, bookings


def test_history_detail_auth_roles_bounds_projection_and_states(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario, bookings = _four_states(client, airports)
    anonymous = iam_support.new_client()
    assert anonymous.get("/api/v1/me/operator-bookings/history").status_code == 401
    assert anonymous.get(f"/api/v1/me/operator-bookings/{bookings[0]['id']}").status_code == 401
    anonymous.close()
    customer = iam_support.new_client()
    _register_limiter.clear()
    iam_support.register_verify_login(customer)
    assert customer.get("/api/v1/me/operator-bookings/history").status_code == 403
    customer.close()

    for role in _ROLES:
        actor = _actor(scenario["operator"]["id"], role)
        history = actor.get("/api/v1/me/operator-bookings/history")
        assert history.status_code == 200, history.text
        assert all(set(item) == _SAFE_FIELDS for item in history.json())
        assert all(_FORBIDDEN.isdisjoint(item) for item in history.json())
        assert {item["status"] for item in history.json()} == {
            "PENDING_OPERATOR_CONFIRMATION",
            "CONFIRMED",
            "REJECTED",
            "CANCELLED",
        }
        detail = actor.get(f"/api/v1/me/operator-bookings/{bookings[0]['id']}")
        assert detail.status_code == 200
        assert set(detail.json()) == _SAFE_FIELDS
        assert _FORBIDDEN.isdisjoint(detail.json())
        assert detail.json()["legs"] == [
            {
                "sequence": 1,
                "origin_airport_code": airports[0]["icao_code"],
                "destination_airport_code": airports[1]["icao_code"],
                "departure_at": "2026-12-01T14:00:00Z",
                "passenger_count": 2,
            }
        ]
        actor.close()

    actor = _actor(scenario["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    assert actor.get("/api/v1/me/operator-bookings/history?limit=1").status_code == 200
    assert actor.get("/api/v1/me/operator-bookings/history?limit=100").status_code == 200
    assert actor.get("/api/v1/me/operator-bookings/history?limit=101").status_code == 422
    assert actor.get("/api/v1/me/operator-bookings/history?offset=-1").status_code == 422
    assert actor.get("/api/v1/me/operator-bookings/history?status=UNKNOWN").status_code == 422
    filtered = actor.get("/api/v1/me/operator-bookings/history?status=CONFIRMED")
    assert [item["status"] for item in filtered.json()] == ["CONFIRMED"]
    assert actor.get("/api/v1/me/operator-bookings/not-a-uuid").status_code == 422
    assert actor.get(f"/api/v1/me/operator-bookings/{uuid4()}").status_code == 404
    actor.close()


def test_active_organization_is_authority_for_history_and_detail(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    a = booking_scenario(client, airports)
    a_booking = create_booking(client, a).json()
    b = booking_scenario(client, airports)
    b_booking = create_booking(client, b).json()
    seed_a = _actor(a["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    seed_b = _actor(b["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    seed_a.close()
    seed_b.close()
    org_a = _organization_id(a["operator"]["id"])
    org_b = _organization_id(b["operator"]["id"])
    assert org_a is not None and org_b is not None
    actor = iam_support.new_client()

    def grant(user_id: UUID) -> None:
        with SessionLocal() as session, session.begin():
            session.add_all(
                [
                    OrganizationMembership(
                        user_id=user_id,
                        organization_id=org_a,
                        role=OrganizationRole.OPERATOR_ADMIN,
                    ),
                    OrganizationMembership(
                        user_id=user_id,
                        organization_id=org_b,
                        role=OrganizationRole.OPERATOR_ADMIN,
                    ),
                ]
            )

    _register_limiter.clear()
    iam_support.register_verify_login(actor, before_verify=grant)
    assert actor.get("/api/v1/me/operator-bookings/history").status_code == 403
    forged = uuid4()
    actor.headers["X-Organization-Id"] = str(forged)
    assert actor.get("/api/v1/me/operator-bookings/history").status_code == 403

    actor.headers["X-Organization-Id"] = str(org_a)
    a_history = actor.get("/api/v1/me/operator-bookings/history").json()
    assert [item["id"] for item in a_history] == [a_booking["id"]]
    assert actor.get(f"/api/v1/me/operator-bookings/{a_booking['id']}").status_code == 200
    assert actor.get(f"/api/v1/me/operator-bookings/{b_booking['id']}").status_code == 404

    actor.headers["X-Organization-Id"] = str(org_b)
    b_history = actor.get("/api/v1/me/operator-bookings/history").json()
    assert [item["id"] for item in b_history] == [b_booking["id"]]
    assert actor.get(f"/api/v1/me/operator-bookings/{b_booking['id']}").status_code == 200
    assert actor.get(f"/api/v1/me/operator-bookings/{a_booking['id']}").status_code == 404

    actor.headers["X-Organization-Id"] = str(org_a)
    assert [item["id"] for item in actor.get("/api/v1/me/operator-bookings/history").json()] == [
        a_booking["id"]
    ]
    assert actor.get(f"/api/v1/me/operator-bookings/{a_booking['id']}").status_code == 200
    assert actor.get(f"/api/v1/me/operator-bookings/{b_booking['id']}").status_code == 404
    actor.close()


def test_ordering_query_bounds_read_only_and_existing_contracts(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    bookings = [create_booking(client, scenario).json()]
    bookings.extend(_additional_booking(client, scenario, airports) for _ in range(2))
    tied = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    with SessionLocal() as session, session.begin():
        for item in bookings:
            session.get(Booking, UUID(item["id"])).created_at = tied
    operator_id = UUID(scenario["operator"]["id"])
    selects: list[str] = []

    def count_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        before = _mutable_domain_counts()
        with SessionLocal() as session:
            selects.clear()
            history = BookingService(session).list_history_for_operator(
                operator_id,
                booking_status=None,
                limit=20,
                offset=0,
            )
            assert len(selects) == 2
            assert [str(item.id) for item in history] == sorted(
                (item["id"] for item in bookings), reverse=True
            )
            selects.clear()
            BookingService(session).get_for_operator(UUID(bookings[0]["id"]), operator_id)
            assert len(selects) == 2
            assert not session.new and not session.dirty and not session.deleted
        assert before == _mutable_domain_counts()
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    actor = _actor(scenario["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    expected_ids = sorted((item["id"] for item in bookings), reverse=True)
    first_page = actor.get("/api/v1/me/operator-bookings/history?limit=2&offset=0").json()
    second_page = actor.get("/api/v1/me/operator-bookings/history?limit=2&offset=2").json()
    paged_ids = [item["id"] for item in first_page + second_page]
    assert paged_ids == expected_ids
    assert len(paged_ids) == len(set(paged_ids))
    assert len(actor.get("/api/v1/me/operator-bookings").json()) == 3
    generic = actor.get(f"/api/v1/bookings/{bookings[0]['id']}")
    assert generic.status_code == 200
    assert "platform_fee_minor" in generic.json()
    actor.close()
