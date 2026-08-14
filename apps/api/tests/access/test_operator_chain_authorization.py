"""Phase 9.0.A-2 — operator-chain resource authorization (DB-backed).

Proves cross-operator isolation (Operator A can never read/act on Operator B's
operator, aircraft, offer, booking, admission, evidence, aircraft-authorization, or
eligibility), server-derived operator ownership, body-owner protection, the
active-OPERATOR-organization context rules, and that the customer paths from Phase
9.0.A-1 remain intact. Uses real, distinct OPERATOR principals — never PRODUCT_OWNER.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.domain import (
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
)
from sky_bridge_jet.modules.iam.models import OrganizationMembership

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _future_iso(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _operator_admin(operator_id: str) -> TestClient:
    client, _ = iam_support.operator_role_client(UUID(operator_id), OrganizationRole.OPERATOR_ADMIN)
    return client


def _first_evidence_id(admin: TestClient, operator_id: str) -> str:
    items = admin.get(f"/api/v1/operators/{operator_id}/evidence").json()
    assert items, "scenario operator should have evidence"
    return str(items[0]["id"])


def _submitted_trip(admin: TestClient, airports: list[dict[str, Any]]) -> dict[str, Any]:
    customer_id = str(iam_support.create_customer(admin))
    trip = admin.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer_id,
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
    admin.post(
        f"/api/v1/trip-requests/{trip['id']}/submit", json={"expected_version": trip["version"]}
    )
    return trip


def _offer_body(trip_id: str, operator_id: str, aircraft_id: str) -> dict[str, Any]:
    return {
        "trip_request_id": trip_id,
        "operator_id": operator_id,
        "aircraft_id": aircraft_id,
        "currency": "EUR",
        "operator_amount_minor": 900_000,
        "tax_amount_minor": 40_000,
        "valid_until": _future_iso(),
    }


# --------------------------------------------------------------------------- #
# B — Active OPERATOR organization context
# --------------------------------------------------------------------------- #
@requires_db
def test_single_operator_membership_auto_resolves(admin: TestClient) -> None:
    operator_id = str(iam_support.create_operator(admin))
    client = _operator_admin(operator_id)
    created = client.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator_id,
            "manufacturer": "Cessna",
            "model": "CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 6,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["operator_id"] == operator_id


@requires_db
def test_multiple_operator_memberships_require_explicit_org(admin: TestClient) -> None:
    a_id = iam_support.create_operator(admin)
    b_id = iam_support.create_operator(admin)
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    orgs: dict[UUID, UUID] = {}
    for op in (a_id, b_id):
        orgs[op] = iam_support._grant_membership(
            user_id,
            organization_type=OrganizationType.OPERATOR,
            role=OrganizationRole.OPERATOR_ADMIN,
            operator_id=op,
        )

    def _aircraft_body(op: UUID) -> dict[str, Any]:
        return {
            "operator_id": str(op),
            "manufacturer": "Embraer",
            "model": "Phenom 300",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 7,
        }

    # Ambiguous without a header → 403.
    assert client.post("/api/v1/aircraft", json=_aircraft_body(a_id)).status_code == 403
    # Explicit valid org for A → creates under A.
    ok = client.post(
        "/api/v1/aircraft",
        json=_aircraft_body(a_id),
        headers={"X-Organization-Id": str(orgs[a_id])},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["operator_id"] == str(a_id)
    # A foreign organization id (not a membership) → rejected before any write.
    assert (
        client.post(
            "/api/v1/aircraft",
            json=_aircraft_body(a_id),
            headers={"X-Organization-Id": str(uuid4())},
        ).status_code
        == 403
    )


@requires_db
def test_customer_and_platform_admin_are_not_operator_context(admin: TestClient) -> None:
    operator_id = str(iam_support.create_operator(admin))
    aircraft_body = {
        "operator_id": operator_id,
        "manufacturer": "Cessna",
        "model": "CJ3+",
        "category": "LIGHT_JET",
        "registration": f"EI-{uuid4().hex[:6].upper()}",
        "passenger_capacity": 6,
    }
    # A CUSTOMER principal has no operator context and no operator.manage.
    customer_client, _ = iam_support.customer_owner_client(
        admin, iam_support.create_customer(admin)
    )
    assert customer_client.post("/api/v1/aircraft", json=aircraft_body).status_code == 403
    # A PLATFORM_ADMIN is not an ordinary operator context and lacks operator.manage
    # (only PRODUCT_OWNER holds it as the audited platform exception).
    platform_admin = iam_support.platform_admin_client()
    assert platform_admin.post("/api/v1/aircraft", json=aircraft_body).status_code == 403


@requires_db
def test_revoked_operator_membership_grants_no_context(admin: TestClient) -> None:
    operator_id = str(iam_support.create_operator(admin))
    client = iam_support.new_client()
    user_id = iam_support.register_verify_login(client)
    org_id = iam_support._grant_membership(
        user_id,
        organization_type=OrganizationType.OPERATOR,
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(operator_id),
    )
    with SessionLocal() as session, session.begin():
        membership = (
            session.query(OrganizationMembership)
            .filter(OrganizationMembership.organization_id == org_id)
            .one()
        )
        membership.status = MembershipStatus.REVOKED
    # No active operator membership → no relationship to the operator → concealed 404
    # (the revoked member can no longer even confirm the tenant exists).
    assert client.post(f"/api/v1/operators/{operator_id}/admission").status_code == 404


@requires_db
def test_customer_active_org_behaviour_unchanged(admin: TestClient) -> None:
    """The Phase 9.0.A-1 customer context is not affected by the operator wiring."""
    customer_id = iam_support.create_customer(admin)
    client, _ = iam_support.customer_owner_client(admin, customer_id)
    created = client.post(
        "/api/v1/passengers",
        json={"customer_id": str(customer_id), "first_name": "Ada", "last_name": "B"},
    )
    assert created.status_code == 201, created.text


# --------------------------------------------------------------------------- #
# C — Cross-operator isolation (A must never touch B), every bound route
# --------------------------------------------------------------------------- #
@requires_db
def test_operator_a_cannot_touch_operator_b(admin: TestClient, airports: list) -> None:
    b = iam_support.full_booking_scenario(admin, airports, confirm=False)
    b_evidence = _first_evidence_id(admin, b["operator_id"])
    # Operator A is a *different*, real operator principal.
    a = iam_support.full_booking_scenario(admin, airports, confirm=False)
    a_client = _operator_admin(a["operator_id"])

    op, ac, off, bk = (
        b["operator_id"],
        b["aircraft_id"],
        b["offer_id"],
        b["booking_id"],
    )
    # Reads → concealed 404.
    assert a_client.get(f"/api/v1/operators/{op}").status_code == 404
    assert a_client.get(f"/api/v1/aircraft/{ac}").status_code == 404
    assert a_client.get(f"/api/v1/offers/{off}").status_code == 404
    assert a_client.get(f"/api/v1/bookings/{bk}").status_code == 404
    assert a_client.get(f"/api/v1/operators/{op}/admission").status_code == 404
    assert a_client.get(f"/api/v1/operators/{op}/admission/audit-events").status_code == 404
    assert a_client.get(f"/api/v1/operators/{op}/evidence").status_code == 404
    assert a_client.get(f"/api/v1/evidence/{b_evidence}").status_code == 404
    assert a_client.get(f"/api/v1/evidence/{b_evidence}/audit-events").status_code == 404
    assert a_client.get(f"/api/v1/operators/{op}/aircraft/{ac}/authorization").status_code == 404
    assert a_client.get(f"/api/v1/operators/{op}/eligibility").status_code == 404
    assert a_client.get(f"/api/v1/operators/{op}/aircraft/{ac}/eligibility").status_code == 404
    # Writes → concealed 404, and B's state is untouched (verified afterward).
    assert a_client.patch(f"/api/v1/offers/{off}", json={"operator_notes": "x"}).status_code == 404
    assert a_client.post(f"/api/v1/offers/{off}/submit").status_code == 404
    assert a_client.post(f"/api/v1/offers/{off}/withdraw").status_code == 404
    assert (
        a_client.post(f"/api/v1/bookings/{bk}/confirm", json={"operator_id": op}).status_code == 404
    )
    assert (
        a_client.post(
            f"/api/v1/bookings/{bk}/reject", json={"operator_id": op, "reason": "OTHER"}
        ).status_code
        == 404
    )
    assert (
        a_client.post(f"/api/v1/bookings/{bk}/cancel", json={"actor": "OPERATOR"}).status_code
        == 404
    )
    assert a_client.post(f"/api/v1/operators/{op}/admission").status_code == 404
    assert a_client.post(f"/api/v1/operators/{op}/admission/submit").status_code == 404
    assert (
        a_client.post(
            f"/api/v1/operators/{op}/evidence",
            json={
                "evidence_type": "INSURANCE",
                "insurer_name": "X",
                "reference_number": "R",
                "expiry_date": _future_iso(365),
            },
        ).status_code
        == 404
    )
    assert (
        a_client.post(
            f"/api/v1/operators/{op}/aircraft/{ac}/authorization", json={"authority_basis": "OWNED"}
        ).status_code
        == 404
    )
    assert (
        a_client.post(f"/api/v1/operators/{op}/aircraft/{ac}/authorization/submit").status_code
        == 404
    )

    # B's booking and offer are unchanged (checked via the platform admin).
    assert admin.get(f"/api/v1/bookings/{bk}").json()["status"] == "PENDING_OPERATOR_CONFIRMATION"
    assert admin.get(f"/api/v1/offers/{off}").json()["status"] in ("SELECTED", "SUBMITTED")


# --------------------------------------------------------------------------- #
# D — Body-supplied owner-id protection
# --------------------------------------------------------------------------- #
@requires_db
def test_body_operator_id_cannot_transfer_ownership(admin: TestClient, airports: list) -> None:
    a = iam_support.full_booking_scenario(admin, airports, confirm=False)
    b_id = str(iam_support.create_operator(admin))
    a_client = _operator_admin(a["operator_id"])

    # A supplies B's operator_id when creating an aircraft → concealed 404 (A's active
    # operator is derived server-side; the body may only confirm it).
    assert (
        a_client.post(
            "/api/v1/aircraft",
            json={
                "operator_id": b_id,
                "manufacturer": "Cessna",
                "model": "CJ3+",
                "category": "LIGHT_JET",
                "registration": f"EI-{uuid4().hex[:6].upper()}",
                "passenger_capacity": 6,
            },
        ).status_code
        == 404
    )
    # A supplies B's operator_id when creating an offer → concealed 404.
    trip = _submitted_trip(admin, airports)
    assert (
        a_client.post(
            "/api/v1/offers", json=_offer_body(trip["id"], b_id, a["aircraft_id"])
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# E — Operator-side booking behaviour
# --------------------------------------------------------------------------- #
@requires_db
def test_owning_operator_confirms_its_booking(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    op_client = _operator_admin(s["operator_id"])
    confirmed = op_client.post(
        f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": s["operator_id"]}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"


@requires_db
def test_body_operator_id_mismatch_is_a_domain_conflict_not_an_escalation(
    admin: TestClient, airports: list
) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    other = str(iam_support.create_operator(admin))
    op_client = _operator_admin(s["operator_id"])
    # A owns the booking (authorized), but the body names another operator → the domain
    # mismatch check fires (409); the body can never authorize a different operator.
    resp = op_client.post(
        f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": other}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "operator_mismatch"
    assert admin.get(f"/api/v1/bookings/{s['booking_id']}").json()["status"] == (
        "PENDING_OPERATOR_CONFIRMATION"
    )


@requires_db
def test_customer_cannot_use_operator_booking_decisions(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    customer_client, _ = iam_support.customer_owner_client(admin, UUID(s["customer_id"]))
    # The owning customer has no booking.decide permission and is not an operator member.
    assert (
        customer_client.post(
            f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": s["operator_id"]}
        ).status_code
        == 404
    )
    assert (
        customer_client.post(
            f"/api/v1/bookings/{s['booking_id']}/reject",
            json={"operator_id": s["operator_id"], "reason": "OTHER"},
        ).status_code
        == 404
    )


@requires_db
def test_operator_lifecycle_conflict_is_409(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    op_client = _operator_admin(s["operator_id"])
    first = op_client.post(
        f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": s["operator_id"]}
    )
    assert first.status_code == 200
    second = op_client.post(
        f"/api/v1/bookings/{s['booking_id']}/confirm", json={"operator_id": s["operator_id"]}
    )
    assert second.status_code == 409


@requires_db
def test_owning_operator_can_cancel_its_booking(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=True)
    op_client = _operator_admin(s["operator_id"])
    cancelled = op_client.post(
        f"/api/v1/bookings/{s['booking_id']}/cancel", json={"actor": "OPERATOR"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"


# --------------------------------------------------------------------------- #
# F — Operator-side offer behaviour
# --------------------------------------------------------------------------- #
@requires_db
def test_owning_operator_creates_and_manages_its_offer(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    op_client = _operator_admin(s["operator_id"])
    trip = _submitted_trip(admin, airports)
    created = op_client.post(
        "/api/v1/offers", json=_offer_body(trip["id"], s["operator_id"], s["aircraft_id"])
    )
    assert created.status_code == 201, created.text
    offer = created.json()
    assert offer["operator_id"] == s["operator_id"]  # server-derived
    # The owning operator can drive its own offer lifecycle.
    assert (
        op_client.patch(
            f"/api/v1/offers/{offer['id']}", json={"operator_notes": "updated"}
        ).status_code
        == 200
    )
    assert op_client.post(f"/api/v1/offers/{offer['id']}/submit").status_code == 200
    assert op_client.post(f"/api/v1/offers/{offer['id']}/withdraw").status_code == 200


# --------------------------------------------------------------------------- #
# G — Operator-self compliance behaviour
# --------------------------------------------------------------------------- #
@requires_db
def test_operator_manages_its_own_compliance_only(admin: TestClient, airports: list) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    op_client = _operator_admin(s["operator_id"])
    # Own operator: reads succeed.
    assert op_client.get(f"/api/v1/operators/{s['operator_id']}/admission").status_code == 200
    assert op_client.get(f"/api/v1/operators/{s['operator_id']}/evidence").status_code == 200
    assert op_client.get(f"/api/v1/operators/{s['operator_id']}/eligibility").status_code == 200
    assert (
        op_client.get(
            f"/api/v1/operators/{s['operator_id']}/aircraft/{s['aircraft_id']}/authorization"
        ).status_code
        == 200
    )
    # An aircraft that is not this operator's → concealed 404 even for the owner.
    foreign = iam_support.full_booking_scenario(admin, airports, confirm=False)
    assert (
        op_client.get(
            f"/api/v1/operators/{s['operator_id']}/aircraft/{foreign['aircraft_id']}/authorization"
        ).status_code
        == 404
    )
    assert (
        op_client.get(
            f"/api/v1/operators/{s['operator_id']}/aircraft/{foreign['aircraft_id']}/eligibility"
        ).status_code
        == 404
    )


@requires_db
def test_operator_cannot_review_compliance(admin: TestClient, airports: list) -> None:
    """Review stays platform-only (compliance.review); operators never gain it."""
    s = iam_support.full_booking_scenario(admin, airports, confirm=False)
    op_client = _operator_admin(s["operator_id"])
    evidence_id = _first_evidence_id(admin, s["operator_id"])
    # Even for its OWN evidence, an operator cannot perform platform review.
    assert (
        op_client.post(
            f"/api/v1/evidence/{evidence_id}/review",
            json={"action": "VERIFY", "actor_type": "PLATFORM_REVIEWER"},
        ).status_code
        == 403
    )
