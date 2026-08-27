from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import iam_support
from fastapi.testclient import TestClient
from sqlalchemy import event

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.compliance.domain import AircraftAuthorizationStatus
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.core_aviation.models import Aircraft, TripRequest
from sky_bridge_jet.modules.core_aviation.services import OperatorService
from sky_bridge_jet.modules.financials.models import ProviderWebhookEvent
from sky_bridge_jet.modules.iam.domain import (
    OrganizationRole,
    Permission,
    permissions_for_role,
)
from sky_bridge_jet.modules.iam.models import Organization
from sky_bridge_jet.modules.iam.router import _register_limiter
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation

from ._support import (
    create_aircraft,
    create_customer,
    create_operator,
    submitted_trip,
)

_ROLES = (
    OrganizationRole.OPERATOR_ADMIN,
    OrganizationRole.OPERATOR_SALES,
    OrganizationRole.OPERATOR_OPERATIONS,
    OrganizationRole.OPERATOR_FINANCE,
    OrganizationRole.OPERATOR_COMPLIANCE,
)


def _actor(operator_id: str, role: OrganizationRole) -> TestClient:
    with SessionLocal() as session:
        organization_id = (
            session.query(Organization.id).filter_by(operator_id=UUID(operator_id)).scalar()
        )
    if organization_id is None:
        actor, organization_id = iam_support.operator_role_client(UUID(operator_id), role)
    else:
        actor = iam_support.member_client_for_org(organization_id, role)
    actor.headers["X-Organization-Id"] = str(organization_id)
    return actor


def _counts() -> tuple[int, ...]:
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


def test_operator_aircraft_auth_roles_tenant_projection_and_bounds(
    client: TestClient,
) -> None:
    anonymous_actor = iam_support.new_client()
    assert anonymous_actor.get("/api/v1/me/operator-aircraft").status_code == 401
    denied_offer_body = {
        "trip_request_id": str(uuid4()),
        "aircraft_id": str(uuid4()),
        "currency": "EUR",
        "operator_amount_minor": 100_000,
    }
    assert (
        anonymous_actor.post("/api/v1/me/operator-offers", json=denied_offer_body).status_code
        == 401
    )
    anonymous_actor.close()
    customer_actor = iam_support.new_client()
    iam_support.register_verify_login(customer_actor)
    assert customer_actor.get("/api/v1/me/operator-aircraft").status_code == 403
    assert (
        customer_actor.post("/api/v1/me/operator-offers", json=denied_offer_body).status_code == 403
    )
    customer_actor.close()

    empty_operator = create_operator(client)
    _register_limiter.clear()
    empty_actor = _actor(empty_operator["id"], OrganizationRole.OPERATOR_SALES)
    assert empty_actor.get("/api/v1/me/operator-aircraft").json() == []
    empty_actor.close()

    operator_a = create_operator(client)
    a2 = create_aircraft(client, operator_a["id"])
    a1 = create_aircraft(client, operator_a["id"])
    operator_b = create_operator(client)
    foreign = create_aircraft(client, operator_b["id"])

    expected_fields = {
        "id",
        "registration",
        "manufacturer",
        "model",
        "category",
        "passenger_capacity",
        "status",
        "eligible",
    }
    for role in _ROLES:
        _register_limiter.clear()
        actor = _actor(operator_a["id"], role)
        response = actor.get("/api/v1/me/operator-aircraft?limit=100")
        assert response.status_code == 200, response.text
        body = response.json()
        own = [item for item in body if item["id"] in {a1["id"], a2["id"]}]
        assert [item["registration"] for item in own] == sorted(
            [a1["registration"], a2["registration"]]
        )
        assert all(set(item) == expected_fields for item in own)
        assert all(item["eligible"] is True for item in own)
        assert foreign["id"] not in response.text
        actor.close()

    _register_limiter.clear()
    actor = _actor(operator_a["id"], OrganizationRole.OPERATOR_SALES)
    first_page = actor.get("/api/v1/me/operator-aircraft?limit=1").json()
    second_page = actor.get("/api/v1/me/operator-aircraft?limit=1&offset=1").json()
    assert len(first_page) == len(second_page) == 1
    assert first_page[0]["id"] != second_page[0]["id"]
    assert [first_page[0]["registration"], second_page[0]["registration"]] == sorted(
        [a1["registration"], a2["registration"]]
    )
    assert actor.get("/api/v1/me/operator-aircraft?limit=20").status_code == 200
    assert actor.get("/api/v1/me/operator-aircraft?limit=100").status_code == 200
    assert actor.get("/api/v1/me/operator-aircraft?limit=101").status_code == 422
    assert actor.get("/api/v1/me/operator-aircraft?limit=0").status_code == 422
    assert actor.get("/api/v1/me/operator-aircraft?offset=-1").status_code == 422
    actor.headers["X-Organization-Id"] = str(uuid4())
    assert actor.get("/api/v1/me/operator-aircraft").status_code == 403
    actor.close()

    _register_limiter.clear()
    foreign_actor = _actor(operator_b["id"], OrganizationRole.OPERATOR_SALES)
    foreign_collection = foreign_actor.get("/api/v1/me/operator-aircraft").json()
    assert [item["id"] for item in foreign_collection] == [foreign["id"]]
    foreign_actor.close()


def test_operator_aircraft_get_is_fixed_query_and_zero_mutation(client: TestClient) -> None:
    operator = create_operator(client)
    create_aircraft(client, operator["id"])
    create_aircraft(client, operator["id"])
    before = _counts()
    statements = 0

    def count_statement(*_args: object, **_kwargs: object) -> None:
        nonlocal statements
        statements += 1

    with SessionLocal() as session:
        event.listen(session.bind, "before_cursor_execute", count_statement)
        try:
            choices = OperatorService(session).list_operator_aircraft(
                UUID(operator["id"]), limit=100, offset=0
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
    assert len(choices) == 2
    assert statements == 5
    assert _counts() == before


def test_operator_offer_create_derives_operator_and_rejects_authority_fields(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    trip = submitted_trip(client, customer["id"], airports)
    operator_a = create_operator(client)
    owned = create_aircraft(client, operator_a["id"])
    operator_b = create_operator(client)
    foreign = create_aircraft(client, operator_b["id"])
    actor = _actor(operator_a["id"], OrganizationRole.OPERATOR_SALES)
    body = {
        "trip_request_id": trip["id"],
        "aircraft_id": owned["id"],
        "currency": "EUR",
        "operator_amount_minor": 100_000,
        "tax_amount_minor": 1_000,
    }
    response = actor.post("/api/v1/me/operator-offers", json=body)
    assert response.status_code == 201, response.text
    offer = response.json()
    assert offer["operator_id"] == operator_a["id"]
    assert offer["platform_fee_minor"] > 0
    assert offer["total_amount_minor"] == (
        offer["operator_amount_minor"] + offer["platform_fee_minor"] + offer["tax_amount_minor"]
    )
    with SessionLocal() as session:
        persisted = session.get(OperatorOffer, UUID(offer["id"]))
        assert persisted is not None and str(persisted.operator_id) == operator_a["id"]

    foreign_attempt = actor.post(
        "/api/v1/me/operator-offers", json={**body, "aircraft_id": foreign["id"]}
    )
    assert foreign_attempt.status_code in {404, 422}
    forged_operator = actor.post(
        "/api/v1/me/operator-offers", json={**body, "operator_id": operator_b["id"]}
    )
    assert forged_operator.status_code == 422

    stale = create_aircraft(client, operator_a["id"])
    collection = actor.get("/api/v1/me/operator-aircraft?limit=100")
    assert any(item["id"] == stale["id"] and item["eligible"] for item in collection.json())
    with SessionLocal() as session, session.begin():
        authorization = (
            session.query(OperatorAircraftAuthorization)
            .filter_by(operator_id=UUID(operator_a["id"]), aircraft_id=UUID(stale["id"]))
            .one()
        )
        authorization.status = AircraftAuthorizationStatus.SUSPENDED
    stale_trip = submitted_trip(client, customer["id"], airports)
    stale_attempt = actor.post(
        "/api/v1/me/operator-offers",
        json={**body, "trip_request_id": stale_trip["id"], "aircraft_id": stale["id"]},
    )
    assert stale_attempt.status_code == 409
    for field, value in (
        ("customer_id", customer["id"]),
        ("platform_fee_minor", 1),
        ("total_amount_minor", 1),
        ("payment_id", str(uuid4())),
        ("provider", "STRIPE"),
        ("capture", True),
        ("refund", True),
        ("organization_id", str(uuid4())),
    ):
        assert (
            actor.post("/api/v1/me/operator-offers", json={**body, field: value}).status_code == 422
        )

    _register_limiter.clear()
    operator_b_actor = _actor(operator_b["id"], OrganizationRole.OPERATOR_SALES)
    operator_b_response = operator_b_actor.post(
        "/api/v1/me/operator-offers", json={**body, "aircraft_id": foreign["id"]}
    )
    assert operator_b_response.status_code == 201, operator_b_response.text
    assert operator_b_response.json()["operator_id"] == operator_b["id"]
    with SessionLocal() as session:
        persisted_b = session.get(OperatorOffer, UUID(operator_b_response.json()["id"]))
        assert persisted_b is not None and str(persisted_b.operator_id) == operator_b["id"]
    operator_b_actor.close()
    actor.close()


def test_operator_aircraft_and_offer_create_openapi_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/me/operator-aircraft"]["get"]
    assert operation["operationId"] == "listMyOperatorAircraft"
    parameters = {item["name"]: item["schema"] for item in operation["parameters"]}
    assert parameters["limit"]["default"] == 20
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 100
    assert parameters["offset"]["minimum"] == 0
    response = schema["components"]["schemas"]["OperatorAircraftResponse"]
    assert set(response["properties"]) == {
        "id",
        "registration",
        "manufacturer",
        "model",
        "category",
        "passenger_capacity",
        "status",
        "eligible",
    }
    scoped_operation = schema["paths"]["/api/v1/me/operator-offers"]["post"]
    assert scoped_operation["operationId"] == "createMyOperatorOffer"
    create = schema["components"]["schemas"]["ActiveOperatorOfferCreate"]
    assert "operator_id" not in create["properties"]
    assert create["additionalProperties"] is False


def test_scoped_offer_create_role_matrix(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    trip = submitted_trip(client, customer["id"], airports)
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    body = {
        "trip_request_id": trip["id"],
        "aircraft_id": aircraft["id"],
        "currency": "EUR",
        "operator_amount_minor": 100_000,
    }
    for role in (
        OrganizationRole.OPERATOR_OPERATIONS,
        OrganizationRole.OPERATOR_FINANCE,
        OrganizationRole.OPERATOR_COMPLIANCE,
    ):
        _register_limiter.clear()
        actor = _actor(operator["id"], role)
        assert actor.post("/api/v1/me/operator-offers", json=body).status_code == 403
        actor.close()

    _register_limiter.clear()
    admin = _actor(operator["id"], OrganizationRole.OPERATOR_ADMIN)
    assert admin.post("/api/v1/me/operator-offers", json=body).status_code == 201
    admin.close()


def test_aircraft_read_and_offer_manage_role_matrix_is_canonical() -> None:
    for role in _ROLES:
        assert Permission.OPERATOR_READ in permissions_for_role(role)
    assert Permission.OFFER_MANAGE in permissions_for_role(OrganizationRole.OPERATOR_ADMIN)
    assert Permission.OFFER_MANAGE in permissions_for_role(OrganizationRole.OPERATOR_SALES)
    for role in (
        OrganizationRole.OPERATOR_OPERATIONS,
        OrganizationRole.OPERATOR_FINANCE,
        OrganizationRole.OPERATOR_COMPLIANCE,
    ):
        assert Permission.OFFER_MANAGE not in permissions_for_role(role)
