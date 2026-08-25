"""Phase 9.0.A-1 — customer-chain resource authorization (DB-backed).

Proves cross-customer isolation, body-owner protection, active-organization
validation, the 401/403/404 policy, and that confidential offer/booking/payment
reads are not served to ordinary customers (deferred to the 9.0.B safe projection).
"""

from __future__ import annotations

import os

import iam_support
import pytest
from fastapi.testclient import TestClient

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_PASSENGER = {"first_name": "Ada", "last_name": "Byron"}


def _passenger_body(customer_id: str) -> dict:
    return {"customer_id": customer_id, **_PASSENGER}


def _trip_body(customer_id: str, airports: list) -> dict:
    return {
        "customer_id": customer_id,
        "legs": [
            {
                "origin_airport_id": airports[0]["id"],
                "destination_airport_id": airports[1]["id"],
                "departure_at": "2026-12-01T14:00:00+00:00",
                "passenger_count": 1,
            }
        ],
    }


# --------------------------------------------------------------------------- #
# Unauthenticated / permission basics
# --------------------------------------------------------------------------- #
@requires_db
def test_anonymous_is_rejected(admin: TestClient) -> None:
    anon = iam_support.new_client()
    customer_id = str(iam_support.create_customer(admin))
    assert anon.get(f"/api/v1/customers/{customer_id}").status_code == 401
    assert anon.post("/api/v1/passengers", json=_passenger_body(customer_id)).status_code == 401


@requires_db
def test_customer_can_create_and_read_own_resources(admin: TestClient, airports: list) -> None:
    customer_id = str(iam_support.create_customer(admin))
    client, _ = iam_support.customer_owner_client(admin, __import__("uuid").UUID(customer_id))

    # Passenger create derives the customer from the principal (body echoes it).
    created = client.post("/api/v1/passengers", json=_passenger_body(customer_id))
    assert created.status_code == 201, created.text
    passenger_id = created.json()["id"]
    assert created.json()["customer_id"] == customer_id
    assert client.get(f"/api/v1/passengers/{passenger_id}").status_code == 200
    assert client.get(f"/api/v1/customers/{customer_id}").status_code == 200

    # Trip create + lifecycle.
    trip = client.post("/api/v1/trip-requests", json=_trip_body(customer_id, airports))
    assert trip.status_code == 201, trip.text
    trip_id = trip.json()["id"]
    assert client.get(f"/api/v1/trip-requests/{trip_id}").status_code == 200
    submitted = client.post(
        f"/api/v1/trip-requests/{trip_id}/submit",
        json={"expected_version": trip.json()["version"]},
    )
    assert submitted.status_code == 200


# --------------------------------------------------------------------------- #
# Cross-customer isolation (A must never touch B)
# --------------------------------------------------------------------------- #
@requires_db
def test_customer_a_cannot_access_customer_b(admin: TestClient, airports: list) -> None:
    import uuid

    a_id = iam_support.create_customer(admin)
    b_id = iam_support.create_customer(admin)
    a_client, _ = iam_support.customer_owner_client(admin, a_id)
    b_client, _ = iam_support.customer_owner_client(admin, b_id)

    # B creates a passenger and a trip.
    b_passenger = b_client.post("/api/v1/passengers", json=_passenger_body(str(b_id))).json()["id"]
    b_trip = b_client.post("/api/v1/trip-requests", json=_trip_body(str(b_id), airports)).json()[
        "id"
    ]

    # A cannot read B's customer/passenger/trip — existence concealed as 404.
    assert a_client.get(f"/api/v1/customers/{b_id}").status_code == 404
    assert a_client.get(f"/api/v1/passengers/{b_passenger}").status_code == 404
    assert a_client.get(f"/api/v1/trip-requests/{b_trip}").status_code == 404
    # A cannot submit/cancel B's trip.
    assert (
        a_client.post(
            f"/api/v1/trip-requests/{b_trip}/submit", json={"expected_version": 1}
        ).status_code
        == 404
    )
    # A random/nonexistent id is also 404 (no enumeration signal difference).
    assert a_client.get(f"/api/v1/trip-requests/{uuid.uuid4()}").status_code == 404


# --------------------------------------------------------------------------- #
# Body-supplied owner-id protection
# --------------------------------------------------------------------------- #
@requires_db
def test_body_customer_id_cannot_transfer_ownership(admin: TestClient, airports: list) -> None:
    a_id = iam_support.create_customer(admin)
    b_id = iam_support.create_customer(admin)
    a_client, _ = iam_support.customer_owner_client(admin, a_id)

    # A supplies B's customer_id in the body → concealed 404, no passenger for B.
    assert a_client.post("/api/v1/passengers", json=_passenger_body(str(b_id))).status_code == 404
    assert (
        a_client.post("/api/v1/trip-requests", json=_trip_body(str(b_id), airports)).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# Active-organization context
# --------------------------------------------------------------------------- #
@requires_db
def test_single_customer_membership_auto_resolves(admin: TestClient) -> None:
    customer_id = iam_support.create_customer(admin)
    client, _ = iam_support.customer_owner_client(admin, customer_id)
    # No X-Organization-Id header needed.
    assert (
        client.post("/api/v1/passengers", json=_passenger_body(str(customer_id))).status_code == 201
    )


@requires_db
def test_multiple_customer_memberships_require_explicit_org(admin: TestClient) -> None:
    import uuid

    from sky_bridge_jet.db.session import SessionLocal
    from sky_bridge_jet.modules.iam.domain import OrganizationRole, OrganizationType
    from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership

    a_id = iam_support.create_customer(admin)
    b_id = iam_support.create_customer(admin)
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)

    org_ids: dict[uuid.UUID, uuid.UUID] = {}
    with SessionLocal() as session, session.begin():
        for cid in (a_id, b_id):
            org = Organization(
                organization_type=OrganizationType.CUSTOMER,
                display_name="Multi",
                customer_id=cid,
            )
            session.add(org)
            session.flush()
            session.add(
                OrganizationMembership(
                    user_id=user_id,
                    organization_id=org.id,
                    role=OrganizationRole.CUSTOMER_OWNER,
                )
            )
            org_ids[cid] = org.id

    # Ambiguous without a header → 403.
    assert client.post("/api/v1/passengers", json=_passenger_body(str(a_id))).status_code == 403
    # Explicit valid org for A → creates under A.
    ok = client.post(
        "/api/v1/passengers",
        json=_passenger_body(str(a_id)),
        headers={"X-Organization-Id": str(org_ids[a_id])},
    )
    assert ok.status_code == 201
    assert ok.json()["customer_id"] == str(a_id)
    # A foreign organization id (not a membership) → rejected.
    assert (
        client.post(
            "/api/v1/passengers",
            json=_passenger_body(str(a_id)),
            headers={"X-Organization-Id": str(uuid.uuid4())},
        ).status_code
        == 403
    )


@requires_db
def test_operator_organization_cannot_be_customer_context(admin: TestClient) -> None:
    from sky_bridge_jet.modules.iam.domain import OrganizationRole

    operator_id = iam_support.create_operator(admin)
    op_client, _ = iam_support.operator_role_client(operator_id, OrganizationRole.OPERATOR_ADMIN)
    customer_id = str(iam_support.create_customer(admin))
    # An operator principal has no customer context → cannot create a passenger.
    assert (
        op_client.post("/api/v1/passengers", json=_passenger_body(customer_id)).status_code == 403
    )


# --------------------------------------------------------------------------- #
# Confidential reads (offers / bookings / payments)
# --------------------------------------------------------------------------- #
_CONFIDENTIAL_FIELDS = ("operator_amount_minor", "platform_fee_minor")


@requires_db
def test_owning_customer_receives_safe_projection_platform_gets_full(
    admin: TestClient, airports: list
) -> None:
    import uuid

    scenario = iam_support.full_booking_scenario(admin, airports)
    customer_id = uuid.UUID(scenario["customer_id"])
    customer_client, _ = iam_support.customer_owner_client(admin, customer_id)
    trip_id = scenario["trip_id"]
    booking_id = scenario["booking_id"]
    payment_id = scenario["payment_id"]

    # Platform (admin/product owner) receives the full internal response (with the split).
    assert admin.get(f"/api/v1/bookings/{booking_id}").json()["platform_fee_minor"] is not None
    assert admin.get(f"/api/v1/payments/{payment_id}").json()["platform_fee_minor"] is not None

    # Phase 9.0.B: the owning customer now receives a customer-SAFE 200 with no split.
    offers = customer_client.get(f"/api/v1/trip-requests/{trip_id}/offers")
    booking = customer_client.get(f"/api/v1/bookings/{booking_id}")
    payment = customer_client.get(f"/api/v1/payments/{payment_id}")
    booking_payment = customer_client.get(f"/api/v1/bookings/{booking_id}/payment")
    for resp in (offers, booking, payment, booking_payment):
        assert resp.status_code == 200, resp.text
        for field in _CONFIDENTIAL_FIELDS:
            assert field not in resp.text

    # A different customer cannot even learn these exist → 404.
    other_client, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    assert other_client.get(f"/api/v1/bookings/{booking_id}").status_code == 404
    assert other_client.get(f"/api/v1/payments/{payment_id}").status_code == 404
    assert other_client.get(f"/api/v1/trip-requests/{trip_id}/offers").status_code == 404


@requires_db
def test_full_responses_never_reach_a_customer_principal(admin: TestClient, airports: list) -> None:
    """The customer's safe 200 never contains confidential fields (Phase 9.0.B)."""
    import uuid

    scenario = iam_support.full_booking_scenario(admin, airports)
    customer_client, _ = iam_support.customer_owner_client(
        admin, uuid.UUID(scenario["customer_id"])
    )
    response = customer_client.get(f"/api/v1/payments/{scenario['payment_id']}")
    assert response.status_code == 200
    assert "platform_fee_minor" not in response.text
    assert "operator_amount_minor" not in response.text


# --------------------------------------------------------------------------- #
# Phase 9.3.B0 — customer_id is optional confirmation; the server derives it
# --------------------------------------------------------------------------- #
def _passenger_body_no_customer() -> dict:
    return dict(_PASSENGER)


def _trip_body_no_customer(airports: list) -> dict:
    body = _trip_body("", airports)
    body.pop("customer_id")
    return body


@requires_db
def test_passenger_create_derives_customer_when_body_omits_it(admin: TestClient) -> None:
    """A customer may create a passenger without supplying a customer_id; the server
    derives the authoritative customer from the validated active organization."""
    customer_id = iam_support.create_customer(admin)
    client, _ = iam_support.customer_owner_client(admin, customer_id)

    created = client.post("/api/v1/passengers", json=_passenger_body_no_customer())
    assert created.status_code == 201, created.text
    # Ownership is the authoritative customer, never client-chosen.
    assert created.json()["customer_id"] == str(customer_id)


@requires_db
def test_trip_request_create_and_submit_without_body_customer_id(
    admin: TestClient, airports: list
) -> None:
    """A first-time customer can create a DRAFT trip and submit it to SUBMITTED without
    ever discovering an internal customer UUID."""
    customer_id = iam_support.create_customer(admin)
    client, _ = iam_support.customer_owner_client(admin, customer_id)

    created = client.post("/api/v1/trip-requests", json=_trip_body_no_customer(airports))
    assert created.status_code == 201, created.text
    trip = created.json()
    assert trip["customer_id"] == str(customer_id)
    assert trip["status"] == "DRAFT"

    submitted = client.post(
        f"/api/v1/trip-requests/{trip['id']}/submit",
        json={"expected_version": trip["version"]},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "SUBMITTED"


@requires_db
def test_omitted_customer_id_still_requires_a_valid_active_org(admin: TestClient) -> None:
    """Omitting customer_id must not bypass active-organization validation: a forged,
    non-member X-Organization-Id is still rejected."""
    import uuid

    customer_id = iam_support.create_customer(admin)
    client, _ = iam_support.customer_owner_client(admin, customer_id)

    forged = client.post(
        "/api/v1/passengers",
        json=_passenger_body_no_customer(),
        headers={"X-Organization-Id": str(uuid.uuid4())},
    )
    assert forged.status_code == 403, forged.text
