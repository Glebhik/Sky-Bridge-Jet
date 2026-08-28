from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import iam_support
from fastapi.testclient import TestClient
from sqlalchemy import event

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.core_aviation.models import Aircraft
from sky_bridge_jet.modules.core_aviation.schemas import AircraftCreate
from sky_bridge_jet.modules.core_aviation.services import OperatorService
from sky_bridge_jet.modules.iam.domain import OrganizationRole, OrganizationType
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership
from sky_bridge_jet.modules.iam.router import _register_limiter

from ._support import (
    create_aircraft,
    create_customer,
    create_operator,
    make_operator_eligible,
    submitted_trip,
)

_ROLES = (
    OrganizationRole.OPERATOR_ADMIN,
    OrganizationRole.OPERATOR_SALES,
    OrganizationRole.OPERATOR_OPERATIONS,
    OrganizationRole.OPERATOR_FINANCE,
    OrganizationRole.OPERATOR_COMPLIANCE,
)
_SAFE_FIELDS = {
    "id",
    "registration",
    "manufacturer",
    "model",
    "category",
    "passenger_capacity",
    "status",
    "eligible",
}


def _organization_id(operator_id: str) -> UUID | None:
    with SessionLocal() as session:
        organization_id = (
            session.query(Organization.id).filter_by(operator_id=UUID(operator_id)).scalar()
        )
    return organization_id


def _actor(operator_id: str, role: OrganizationRole) -> TestClient:
    organization_id = _organization_id(operator_id)
    if organization_id is None:
        actor, organization_id = iam_support.operator_role_client(UUID(operator_id), role)
    else:
        actor = iam_support.member_client_for_org(organization_id, role)
    actor.headers["X-Organization-Id"] = str(organization_id)
    return actor


def _create_body(**overrides: object) -> dict[str, object]:
    return {
        "registration": f"EI-{uuid4().hex[:6].upper()}",
        "manufacturer": "Cessna",
        "model": "Citation CJ3+",
        "category": "LIGHT_JET",
        "passenger_capacity": 7,
        **overrides,
    }


def test_safe_detail_auth_roles_projection_and_unknown(client: TestClient) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])

    anonymous = iam_support.new_client()
    assert anonymous.get(f"/api/v1/me/operator-aircraft/{aircraft['id']}").status_code == 401
    anonymous.close()
    customer = iam_support.new_client()
    iam_support.register_verify_login(customer)
    assert customer.get(f"/api/v1/me/operator-aircraft/{aircraft['id']}").status_code == 403
    customer.close()

    for role in _ROLES:
        _register_limiter.clear()
        actor = _actor(operator["id"], role)
        response = actor.get(f"/api/v1/me/operator-aircraft/{aircraft['id']}")
        assert response.status_code == 200, response.text
        assert set(response.json()) == _SAFE_FIELDS
        assert response.json()["id"] == aircraft["id"]
        assert response.json()["eligible"] is True
        assert actor.get(f"/api/v1/me/operator-aircraft/{uuid4()}").status_code == 404
        actor.close()


def test_safe_detail_active_organization_is_decisive(client: TestClient) -> None:
    operator_a = create_operator(client)
    aircraft_a = create_aircraft(client, operator_a["id"])
    operator_b = create_operator(client)
    aircraft_b = create_aircraft(client, operator_b["id"])
    actor = iam_support.new_client()
    organizations: dict[str, UUID] = {}

    def grant(user_id: UUID) -> None:
        with SessionLocal() as session, session.begin():
            for label, operator_id in (("a", operator_a["id"]), ("b", operator_b["id"])):
                organization = Organization(
                    organization_type=OrganizationType.OPERATOR,
                    display_name=f"Operator {label.upper()}",
                    operator_id=UUID(operator_id),
                )
                session.add(organization)
                session.flush()
                organizations[label] = organization.id
                session.add(
                    OrganizationMembership(
                        user_id=user_id,
                        organization_id=organization.id,
                        role=OrganizationRole.OPERATOR_ADMIN,
                    )
                )

    iam_support.register_verify_login(actor, before_verify=grant)
    for active, visible, concealed in (
        ("a", aircraft_a, aircraft_b),
        ("b", aircraft_b, aircraft_a),
        ("a", aircraft_a, aircraft_b),
    ):
        actor.headers["X-Organization-Id"] = str(organizations[active])
        assert actor.get(f"/api/v1/me/operator-aircraft/{visible['id']}").status_code == 200
        assert actor.get(f"/api/v1/me/operator-aircraft/{concealed['id']}").status_code == 404

    created_by_org: dict[str, dict[str, object]] = {}
    for active in ("a", "b"):
        actor.headers["X-Organization-Id"] = str(organizations[active])
        response = actor.post("/api/v1/me/operator-aircraft", json=_create_body())
        assert response.status_code == 201, response.text
        assert set(response.json()) == _SAFE_FIELDS
        assert response.json()["eligible"] is False
        created_by_org[active] = response.json()
    with SessionLocal() as session:
        persisted_a = session.get(Aircraft, UUID(str(created_by_org["a"]["id"])))
        persisted_b = session.get(Aircraft, UUID(str(created_by_org["b"]["id"])))
        assert persisted_a is not None and str(persisted_a.operator_id) == operator_a["id"]
        assert persisted_b is not None and str(persisted_b.operator_id) == operator_b["id"]
    actor.headers["X-Organization-Id"] = str(organizations["b"])
    assert actor.get(f"/api/v1/me/operator-aircraft/{created_by_org['a']['id']}").status_code == 404
    actor.headers["X-Organization-Id"] = str(uuid4())
    assert actor.get(f"/api/v1/me/operator-aircraft/{aircraft_a['id']}").status_code == 403
    actor.close()


def test_safe_create_role_authority_schema_ownership_and_duplicate(client: TestClient) -> None:
    operator = create_operator(client)
    with SessionLocal() as session:
        initial_count = session.query(Aircraft).count()
    for role in _ROLES[1:]:
        _register_limiter.clear()
        actor = _actor(operator["id"], role)
        assert actor.post("/api/v1/me/operator-aircraft", json=_create_body()).status_code == 403
        actor.close()
    with SessionLocal() as session:
        assert session.query(Aircraft).count() == initial_count

    _register_limiter.clear()
    admin = _actor(operator["id"], OrganizationRole.OPERATOR_ADMIN)
    body = _create_body(registration="  ei-ab12  ")
    response = admin.post("/api/v1/me/operator-aircraft", json=body)
    assert response.status_code == 201, response.text
    assert set(response.json()) == _SAFE_FIELDS
    assert response.json()["registration"] == "EI-AB12"
    assert response.json()["eligible"] is False
    with SessionLocal() as session:
        persisted = session.get(Aircraft, UUID(response.json()["id"]))
        assert persisted is not None
        assert str(persisted.operator_id) == operator["id"]

    for forbidden in (
        "operator_id",
        "organization_id",
        "eligible",
        "compliance_status",
        "authorization_status",
        "review_status",
        "ownership_transfer",
        "customer_id",
        "payment",
        "payment_id",
        "provider",
        "created_at",
        "updated_at",
    ):
        forged = admin.post(
            "/api/v1/me/operator-aircraft",
            json=_create_body(**{forbidden: str(uuid4())}),
        )
        assert forged.status_code == 422, (forbidden, forged.text)

    duplicate = admin.post("/api/v1/me/operator-aircraft", json=body)
    assert duplicate.status_code == 409
    with SessionLocal() as session:
        assert session.query(Aircraft).filter_by(registration="EI-AB12").count() == 1
    for invalid in (
        _create_body(registration=" "),
        _create_body(registration="A" * 21),
        _create_body(manufacturer=" "),
        _create_body(model="M" * 101),
        _create_body(category="IN_SERVICE"),
        _create_body(passenger_capacity=0),
        _create_body(passenger_capacity=1_001),
        {"registration": "EI-MISSING"},
    ):
        assert admin.post("/api/v1/me/operator-aircraft", json=invalid).status_code == 422
    recovered = admin.post("/api/v1/me/operator-aircraft", json=_create_body())
    assert recovered.status_code == 201
    admin.close()


def test_safe_detail_fixed_query_read_only_and_openapi(client: TestClient) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    before = client.get(f"/api/v1/aircraft/{aircraft['id']}").json()
    statements = 0

    def count_statement(*_args: object, **_kwargs: object) -> None:
        nonlocal statements
        statements += 1

    with SessionLocal() as session:
        event.listen(session.bind, "before_cursor_execute", count_statement)
        try:
            choice = OperatorService(session).get_operator_aircraft(
                UUID(operator["id"]), UUID(aircraft["id"])
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
    assert choice.aircraft.id == UUID(aircraft["id"])
    assert statements == 5
    assert client.get(f"/api/v1/aircraft/{aircraft['id']}").json() == before

    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/v1/me/operator-aircraft/{aircraft_id}"]["get"]
    assert path["operationId"] == "getMyOperatorAircraft"
    create = schema["paths"]["/api/v1/me/operator-aircraft"]["post"]
    assert create["operationId"] == "createMyOperatorAircraft"
    request_ref = create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_name = request_ref.rsplit("/", 1)[-1]
    request_schema = schema["components"]["schemas"][request_name]
    assert set(request_schema["properties"]) == {
        "registration",
        "manufacturer",
        "model",
        "category",
        "passenger_capacity",
    }
    assert request_schema["additionalProperties"] is False
    assert "operator_id" not in request_schema["properties"]


def test_create_and_authoritative_reload_have_fixed_query_shape(client: TestClient) -> None:
    operator = create_operator(client)

    def create_and_reload(registration: str) -> int:
        statements = 0

        def count_statement(*_args: object, **_kwargs: object) -> None:
            nonlocal statements
            statements += 1

        with SessionLocal() as session:
            event.listen(session.bind, "before_cursor_execute", count_statement)
            try:
                aircraft = OperatorService(session).create_aircraft(
                    AircraftCreate(
                        operator_id=UUID(operator["id"]),
                        registration=registration,
                        manufacturer="Cessna",
                        model="Citation CJ3+",
                        category="LIGHT_JET",
                        passenger_capacity=7,
                    )
                )
                choice = OperatorService(session).get_operator_aircraft(
                    UUID(operator["id"]), aircraft.id
                )
                assert choice.eligible is False
            finally:
                event.remove(session.bind, "before_cursor_execute", count_statement)
        return statements

    first = create_and_reload(f"EI-{uuid4().hex[:6].upper()}")
    for _ in range(10):
        with SessionLocal() as session:
            OperatorService(session).create_aircraft(
                AircraftCreate(
                    operator_id=UUID(operator["id"]),
                    registration=f"EI-{uuid4().hex[:6].upper()}",
                    manufacturer="Cessna",
                    model="Citation CJ3+",
                    category="LIGHT_JET",
                    passenger_capacity=7,
                )
            )
    second = create_and_reload(f"EI-{uuid4().hex[:6].upper()}")
    assert first == second == 7


def test_scoped_create_does_not_bypass_offer_compliance(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    customer = create_customer(client)
    trip = submitted_trip(client, customer["id"], airports)
    operator = create_operator(client)
    admin = _actor(operator["id"], OrganizationRole.OPERATOR_ADMIN)
    created = admin.post("/api/v1/me/operator-aircraft", json=_create_body())
    assert created.status_code == 201, created.text
    assert created.json()["eligible"] is False

    offer = admin.post(
        "/api/v1/me/operator-offers",
        json={
            "trip_request_id": trip["id"],
            "aircraft_id": created.json()["id"],
            "currency": "EUR",
            "operator_amount_minor": 100_000,
        },
    )
    assert offer.status_code == 409
    assert offer.json()["error"]["code"] == "compliance_not_satisfied"

    make_operator_eligible(client, operator["id"], created.json()["id"])
    accepted = admin.post(
        "/api/v1/me/operator-offers",
        json={
            "trip_request_id": trip["id"],
            "aircraft_id": created.json()["id"],
            "currency": "EUR",
            "operator_amount_minor": 100_000,
        },
    )
    assert accepted.status_code == 201, accepted.text
    admin.close()
