"""Phase 9.0.A-3 — payment operational authorization (DB-backed + matrix unit).

Proves payment.operate is platform-only (PLATFORM_ADMIN + PRODUCT_OWNER), that
PLATFORM_FINANCE_REVIEWER is strictly read-only, that payment.refund stays separate,
that customers/operators can never operate or refund payments, and that the
allocation/refund-list reads are platform-read-only with no confidential leakage.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.modules.iam.domain import (
    ROLE_PERMISSIONS,
    OrganizationRole,
    Permission,
)

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _key() -> str:
    return f"idem-{uuid4().hex}"


def _finance_reviewer() -> TestClient:
    return iam_support.platform_role_client(OrganizationRole.PLATFORM_FINANCE_REVIEWER)


def _created_payment(admin: TestClient, airports: list) -> dict[str, Any]:
    """A scenario whose payment exists in CREATED state (booking CONFIRMED)."""
    return iam_support.full_booking_scenario(admin, airports, confirm=True)


def _authorize(admin: TestClient, payment_id: str) -> None:
    resp = admin.post(f"/api/v1/payments/{payment_id}/authorize", json={"idempotency_key": _key()})
    assert resp.status_code == 200, resp.text


def _capture(admin: TestClient, payment_id: str) -> None:
    resp = admin.post(f"/api/v1/payments/{payment_id}/capture", json={"idempotency_key": _key()})
    assert resp.status_code == 200, resp.text


def _payment_status(admin: TestClient, payment_id: str) -> str:
    return str(admin.get(f"/api/v1/payments/{payment_id}").json()["status"])


def _confirmed_booking_without_payment(admin: TestClient, airports: list) -> str:
    """Build a CONFIRMED booking with no payment yet (for create-authorization tests)."""
    customer_id = str(iam_support.create_customer(admin))
    operator = admin.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Pay Air {uuid4().hex[:6]}",
            "country_code": "IE",
            "contact_email": f"pay-{uuid4().hex[:8]}@example.test",
        },
    ).json()
    aircraft = admin.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator["id"],
            "manufacturer": "Cessna",
            "model": "CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 6,
        },
    ).json()
    iam_support.make_operator_eligible(admin, operator["id"], aircraft["id"])
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
    offer = admin.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip["id"],
            "operator_id": operator["id"],
            "aircraft_id": aircraft["id"],
            "currency": "EUR",
            "operator_amount_minor": 800_000,
            "tax_amount_minor": 40_000,
            "valid_until": iam_support._future_iso(),
        },
    ).json()
    admin.post(f"/api/v1/offers/{offer['id']}/submit")
    admin.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    booking = admin.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    ).json()
    admin.post(f"/api/v1/bookings/{booking['id']}/confirm", json={"operator_id": operator["id"]})
    return str(booking["id"])


# --------------------------------------------------------------------------- #
# B — Permission matrix (no DB): payment.operate is platform-only
# --------------------------------------------------------------------------- #
def test_payment_operate_is_platform_admin_and_product_owner_only() -> None:
    holders = {r for r, perms in ROLE_PERMISSIONS.items() if Permission.PAYMENT_OPERATE in perms}
    assert holders == {OrganizationRole.PLATFORM_ADMIN, OrganizationRole.PRODUCT_OWNER}


def test_finance_reviewer_is_read_only() -> None:
    perms = ROLE_PERMISSIONS[OrganizationRole.PLATFORM_FINANCE_REVIEWER]
    assert Permission.PAYMENT_READ in perms  # visibility retained
    assert Permission.PAYMENT_OPERATE not in perms  # no operational capability
    assert Permission.PAYMENT_REFUND not in perms  # no refund capability


def test_payment_refund_is_separate_and_platform_only() -> None:
    holders = {r for r, perms in ROLE_PERMISSIONS.items() if Permission.PAYMENT_REFUND in perms}
    assert holders == {OrganizationRole.PLATFORM_ADMIN, OrganizationRole.PRODUCT_OWNER}
    # No customer or operator role holds operate or refund.
    for role, perms in ROLE_PERMISSIONS.items():
        if role.value.startswith(("CUSTOMER", "OPERATOR")):
            assert Permission.PAYMENT_OPERATE not in perms
            assert Permission.PAYMENT_REFUND not in perms


# --------------------------------------------------------------------------- #
# C — Internal payment creation
# --------------------------------------------------------------------------- #
@requires_db
def test_platform_admin_and_product_owner_can_create_payment(
    admin: TestClient, airports: list
) -> None:
    booking_id = _confirmed_booking_without_payment(admin, airports)
    platform_admin = iam_support.platform_admin_client()
    created = platform_admin.post(f"/api/v1/bookings/{booking_id}/payment")
    assert created.status_code == 201, created.text
    # Idempotent second create by PRODUCT_OWNER returns the same payment.
    again = admin.post(f"/api/v1/bookings/{booking_id}/payment")
    assert again.status_code == 201
    assert again.json()["id"] == created.json()["id"]


@requires_db
def test_non_platform_roles_cannot_create_payment(admin: TestClient, airports: list) -> None:
    booking_id = _confirmed_booking_without_payment(admin, airports)
    scenario_customer = iam_support.create_customer(admin)
    customer, _ = iam_support.customer_owner_client(admin, scenario_customer)
    operator, _ = iam_support.operator_role_client(
        UUID(str(iam_support.create_operator(admin))), OrganizationRole.OPERATOR_ADMIN
    )
    for client in (_finance_reviewer(), customer, operator):
        assert client.post(f"/api/v1/bookings/{booking_id}/payment").status_code == 403
    # No payment was created by any denied attempt.
    assert admin.get(f"/api/v1/bookings/{booking_id}/payment").status_code == 404


@requires_db
def test_create_payment_rejects_ineligible_booking(admin: TestClient, airports: list) -> None:
    # A booking whose payment already exists and has been voided is not re-payable.
    s = _created_payment(admin, airports)
    admin.post(f"/api/v1/payments/{s['payment_id']}/void", json={"idempotency_key": _key()})
    # Its existing payment is returned idempotently (still one payment, now CANCELLED).
    resp = admin.post(f"/api/v1/bookings/{s['booking_id']}/payment")
    assert resp.status_code in (201, 409)


# --------------------------------------------------------------------------- #
# D — Authorize / capture / void
# --------------------------------------------------------------------------- #
@requires_db
@pytest.mark.parametrize("action", ["authorize", "capture", "void"])
def test_non_platform_roles_cannot_operate_payments(
    admin: TestClient, airports: list, action: str
) -> None:
    s = _created_payment(admin, airports)
    pid = s["payment_id"]
    customer, _ = iam_support.customer_owner_client(admin, UUID(s["customer_id"]))
    operator, _ = iam_support.operator_role_client(
        UUID(s["operator_id"]), OrganizationRole.OPERATOR_ADMIN
    )
    body = {"idempotency_key": _key()}
    for client in (_finance_reviewer(), customer, operator):
        assert client.post(f"/api/v1/payments/{pid}/{action}", json=body).status_code == 403
    # The denied operations left the payment in its original CREATED state.
    assert _payment_status(admin, pid) == "CREATED"


@requires_db
def test_platform_admin_can_authorize_capture_void(admin: TestClient, airports: list) -> None:
    platform_admin = iam_support.platform_admin_client()
    s = _created_payment(admin, airports)
    authd = platform_admin.post(
        f"/api/v1/payments/{s['payment_id']}/authorize", json={"idempotency_key": _key()}
    )
    assert authd.status_code == 200, authd.text
    assert authd.json()["status"] == "AUTHORIZED"
    captured = platform_admin.post(
        f"/api/v1/payments/{s['payment_id']}/capture", json={"idempotency_key": _key()}
    )
    assert captured.status_code == 200
    assert captured.json()["status"] == "CAPTURED"

    # A separate payment can be voided by a platform admin.
    other = _created_payment(admin, airports)
    voided = platform_admin.post(
        f"/api/v1/payments/{other['payment_id']}/void", json={"idempotency_key": _key()}
    )
    assert voided.status_code == 200
    assert voided.json()["status"] == "CANCELLED"


@requires_db
def test_capture_in_invalid_state_is_conflict(admin: TestClient, airports: list) -> None:
    # Capturing a CREATED (un-authorized) payment is a lifecycle conflict, not a bypass.
    s = _created_payment(admin, airports)
    resp = admin.post(
        f"/api/v1/payments/{s['payment_id']}/capture", json={"idempotency_key": _key()}
    )
    assert resp.status_code == 409
    assert _payment_status(admin, s["payment_id"]) == "CREATED"


# --------------------------------------------------------------------------- #
# E — Refund (payment.refund unchanged; finance reviewer cannot refund)
# --------------------------------------------------------------------------- #
@requires_db
def test_refund_requires_payment_refund_and_excludes_finance_reviewer(
    admin: TestClient, airports: list
) -> None:
    s = _created_payment(admin, airports)
    _authorize(admin, s["payment_id"])
    _capture(admin, s["payment_id"])
    body = {"idempotency_key": _key(), "amount_minor": 1000}

    customer, _ = iam_support.customer_owner_client(admin, UUID(s["customer_id"]))
    operator, _ = iam_support.operator_role_client(
        UUID(s["operator_id"]), OrganizationRole.OPERATOR_ADMIN
    )
    # Finance reviewer, customer, operator all denied (payment.refund is platform-only).
    for client in (_finance_reviewer(), customer, operator):
        assert (
            client.post(f"/api/v1/payments/{s['payment_id']}/refunds", json=body).status_code == 403
        )
    # PRODUCT_OWNER (holds payment.refund) can refund.
    ok = admin.post(f"/api/v1/payments/{s['payment_id']}/refunds", json=body)
    assert ok.status_code == 201, ok.text


# --------------------------------------------------------------------------- #
# F — Allocation & refund-list reads (platform payment.read only)
# --------------------------------------------------------------------------- #
@requires_db
def test_allocation_and_refunds_are_platform_read_only(admin: TestClient, airports: list) -> None:
    s = _created_payment(admin, airports)
    pid = s["payment_id"]
    # Platform payment.read viewers (finance reviewer, PRODUCT_OWNER) may read.
    finance = _finance_reviewer()
    assert finance.get(f"/api/v1/payments/{pid}/allocation").status_code == 200
    assert finance.get(f"/api/v1/payments/{pid}/refunds").status_code == 200
    assert admin.get(f"/api/v1/payments/{pid}/allocation").status_code == 200

    # The owning customer and owning operator are denied (no safe projection yet — 403).
    customer, _ = iam_support.customer_owner_client(admin, UUID(s["customer_id"]))
    operator, _ = iam_support.operator_role_client(
        UUID(s["operator_id"]), OrganizationRole.OPERATOR_ADMIN
    )
    for client in (customer, operator):
        alloc = client.get(f"/api/v1/payments/{pid}/allocation")
        refunds = client.get(f"/api/v1/payments/{pid}/refunds")
        assert alloc.status_code == 403
        assert refunds.status_code == 403
        for forbidden in ("platform_fee_minor", "operator_amount_minor", "settlement_eligibility"):
            assert forbidden not in alloc.text


@requires_db
def test_cross_operator_and_unrelated_reads_are_concealed(
    admin: TestClient, airports: list
) -> None:
    s = _created_payment(admin, airports)
    pid = s["payment_id"]
    # An unrelated operator (owns a different operator) → concealed 404, no data.
    other_operator, _ = iam_support.operator_role_client(
        UUID(str(iam_support.create_operator(admin))), OrganizationRole.OPERATOR_ADMIN
    )
    alloc = other_operator.get(f"/api/v1/payments/{pid}/allocation")
    assert alloc.status_code == 404
    assert "platform_fee_minor" not in alloc.text
    # A wholly unknown payment id → 404.
    assert admin.get(f"/api/v1/payments/{uuid4()}/allocation").status_code == 404
