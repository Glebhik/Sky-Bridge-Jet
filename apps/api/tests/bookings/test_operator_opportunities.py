from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import iam_support
from fastapi.testclient import TestClient
from sqlalchemy import event

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.compliance.models import OperatorAdmission
from sky_bridge_jet.modules.core_aviation.models import TripRequest
from sky_bridge_jet.modules.financials.models import ProviderWebhookEvent
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.iam.models import Organization
from sky_bridge_jet.modules.iam.router import _register_limiter
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.opportunities import OperatorOpportunityService
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation

from ._support import (
    create_aircraft,
    create_customer,
    create_operator,
    draft_offer,
    requires_db,
    submitted_trip,
)

pytestmark = requires_db
_ROLES = (
    OrganizationRole.OPERATOR_ADMIN,
    OrganizationRole.OPERATOR_SALES,
    OrganizationRole.OPERATOR_OPERATIONS,
    OrganizationRole.OPERATOR_FINANCE,
    OrganizationRole.OPERATOR_COMPLIANCE,
)


def _operator_client(operator_id: str, role: OrganizationRole) -> TestClient:
    with SessionLocal() as session:
        organization_id = (
            session.query(Organization.id).filter_by(operator_id=UUID(operator_id)).scalar()
        )
    if organization_id is None:
        client, organization_id = iam_support.operator_role_client(UUID(operator_id), role)
    else:
        client = iam_support.member_client_for_org(organization_id, role)
    client.headers["X-Organization-Id"] = str(organization_id)
    return client


def _counts() -> tuple[int, ...]:
    with SessionLocal() as session:
        return tuple(
            session.query(model).count()
            for model in (
                TripRequest,
                OperatorOffer,
                Booking,
                Payment,
                PaymentOperation,
                OperatorAdmission,
                ProviderWebhookEvent,
            )
        )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_opportunity_auth_context_role_and_admission_policy(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    assert TestClient(client.app).get("/api/v1/me/operator-opportunities").status_code == 401

    customer_actor = iam_support.new_client()
    iam_support.register_verify_login(customer_actor)
    assert customer_actor.get("/api/v1/me/operator-opportunities").status_code == 403
    customer_actor.headers["X-Organization-Id"] = str(uuid4())
    assert customer_actor.get("/api/v1/me/operator-opportunities").status_code == 403
    customer_actor.close()

    customer = create_customer(client)
    trip = submitted_trip(client, customer["id"], airports)
    operator = create_operator(client)
    unadmitted = _operator_client(operator["id"], OrganizationRole.OPERATOR_SALES)
    assert unadmitted.get("/api/v1/me/operator-opportunities").json() == []
    unadmitted.close()

    create_aircraft(client, operator["id"])
    for role in _ROLES:
        _register_limiter.clear()
        actor = _operator_client(operator["id"], role)
        response = actor.get("/api/v1/me/operator-opportunities?limit=100")
        assert response.status_code == 200, response.text
        assert trip["id"] in {item["trip_request_id"] for item in response.json()}
        actor.close()


def test_opportunities_are_minimal_state_filtered_and_own_offer_safe(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    included = submitted_trip(client, customer["id"], airports)
    draft = client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer["id"],
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2027-01-02T12:00:00+00:00",
                    "passenger_count": 3,
                }
            ],
            "requirements": {
                "baggage_notes": "private luggage detail",
                "catering_notes": "private catering detail",
                "special_assistance_notes": "private medical detail",
                "customer_notes": "private customer note",
            },
        },
    ).json()
    own_operator = create_operator(client)
    own_aircraft = create_aircraft(client, own_operator["id"])
    own = draft_offer(
        client,
        trip_request_id=included["id"],
        operator_id=own_operator["id"],
        aircraft_id=own_aircraft["id"],
    )
    foreign_operator = create_operator(client)
    foreign_aircraft = create_aircraft(client, foreign_operator["id"])
    foreign = draft_offer(
        client,
        trip_request_id=included["id"],
        operator_id=foreign_operator["id"],
        aircraft_id=foreign_aircraft["id"],
    )
    own_submitted_trip = submitted_trip(client, customer["id"], airports)
    own_submitted = draft_offer(
        client,
        trip_request_id=own_submitted_trip["id"],
        operator_id=own_operator["id"],
        aircraft_id=own_aircraft["id"],
    )
    assert client.post(f"/api/v1/offers/{own_submitted['id']}/submit").status_code == 200
    foreign_only_trip = submitted_trip(client, customer["id"], airports)
    foreign_only = draft_offer(
        client,
        trip_request_id=foreign_only_trip["id"],
        operator_id=foreign_operator["id"],
        aircraft_id=foreign_aircraft["id"],
    )
    no_offer_trip = submitted_trip(client, customer["id"], airports)

    actor = _operator_client(own_operator["id"], OrganizationRole.OPERATOR_SALES)
    response = actor.get("/api/v1/me/operator-opportunities?limit=100")
    assert response.status_code == 200, response.text
    body = response.json()
    matching = [item for item in body if item["trip_request_id"] == included["id"]]
    assert len(matching) == 1
    item = matching[0]
    assert item["status"] == "SUBMITTED"
    assert item["own_offers"] == [{"offer_id": own["id"], "status": "DRAFT"}]
    assert foreign["id"] not in response.text
    by_trip = {entry["trip_request_id"]: entry for entry in body}
    assert by_trip[own_submitted_trip["id"]]["own_offers"] == [
        {"offer_id": own_submitted["id"], "status": "SUBMITTED"}
    ]
    assert by_trip[foreign_only_trip["id"]]["own_offers"] == []
    assert foreign_only["id"] not in response.text
    assert by_trip[no_offer_trip["id"]]["own_offers"] == []
    assert draft["id"] not in {entry["trip_request_id"] for entry in body}
    forbidden = {
        "customer_id",
        "customer_organization_id",
        "email",
        "phone",
        "passengers",
        "passenger_id",
        "first_name",
        "last_name",
        "date_of_birth",
        "nationality",
        "passport",
        "requirements",
        "baggage_notes",
        "catering_notes",
        "special_assistance_notes",
        "customer_notes",
        "operator_id",
        "aircraft_id",
        "operator_amount_minor",
        "platform_fee_minor",
        "tax_amount_minor",
        "total_amount_minor",
        "payment",
        "provider",
    }
    assert forbidden.isdisjoint(_all_keys(body))
    actor.close()


def test_opportunity_ordering_pagination_validation_and_empty_page(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    trips = [submitted_trip(client, customer["id"], airports) for _ in range(3)]
    tied = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    with SessionLocal() as session, session.begin():
        for trip in trips:
            session.get(TripRequest, UUID(trip["id"])).created_at = tied
    operator = create_operator(client)
    create_aircraft(client, operator["id"])
    actor = _operator_client(operator["id"], OrganizationRole.OPERATOR_ADMIN)
    expected = sorted(trip["id"] for trip in trips)
    all_items = actor.get("/api/v1/me/operator-opportunities?limit=100").json()
    actual = [item["trip_request_id"] for item in all_items if item["trip_request_id"] in expected]
    assert actual == expected
    page_one = actor.get("/api/v1/me/operator-opportunities?limit=1&offset=0")
    page_two = actor.get("/api/v1/me/operator-opportunities?limit=1&offset=1")
    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()[0]["trip_request_id"] == all_items[0]["trip_request_id"]
    assert page_two.json()[0]["trip_request_id"] == all_items[1]["trip_request_id"]
    assert actor.get("/api/v1/me/operator-opportunities?limit=20").status_code == 200
    assert actor.get("/api/v1/me/operator-opportunities?limit=100").status_code == 200
    assert actor.get("/api/v1/me/operator-opportunities?limit=101").status_code == 422
    assert actor.get("/api/v1/me/operator-opportunities?offset=-1").status_code == 422
    assert actor.get("/api/v1/me/operator-opportunities?offset=100000").json() == []
    actor.close()


def test_opportunity_get_is_fixed_query_and_has_zero_domain_mutation(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    trip = submitted_trip(client, customer["id"], airports)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    draft_offer(
        client,
        trip_request_id=trip["id"],
        operator_id=operator["id"],
        aircraft_id=aircraft["id"],
    )
    before = _counts()
    statements = 0

    def count_statement(*_args: object, **_kwargs: object) -> None:
        nonlocal statements
        statements += 1

    with SessionLocal() as session:
        event.listen(session.bind, "before_cursor_execute", count_statement)
        try:
            first = OperatorOpportunityService(session).list_for_operator(
                UUID(operator["id"]), limit=20, offset=0
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
    assert len(first) >= 1
    assert statements == 6
    assert _counts() == before


def test_opportunity_openapi_is_bounded_and_private(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/me/operator-opportunities"][
        "get"
    ]
    assert operation["operationId"] == "listMyOperatorOpportunities"
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 20,
        "title": "Limit",
    }
    assert parameters["offset"]["schema"]["minimum"] == 0
    schema = client.get("/openapi.json").text
    response_name = "OperatorOpportunityResponse"
    response_schema = client.get("/openapi.json").json()["components"]["schemas"][response_name]
    assert set(response_schema["properties"]) == {
        "trip_request_id",
        "status",
        "legs",
        "own_offers",
        "created_at",
    }
    assert "customer_id" not in str(response_schema)
    assert "/api/v1/me/operator-opportunities" in schema
