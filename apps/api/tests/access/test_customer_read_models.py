"""Phase 9.0.B (C-G) — customer 'my' lists and customer-safe projections (DB-backed).

Proves cross-customer isolation of the ``/me`` list endpoints, bounded pagination, and
that every customer-reachable offer/booking/payment response is the customer-safe
projection with the operator/platform split and internal fields structurally absent —
while operator/platform audiences keep the full internal response.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

# Fields that must never appear in any customer-reachable payload (incl. list items).
FORBIDDEN = (
    "operator_amount_minor",
    "platform_fee_minor",
    "settlement_eligibility",
    "provider_payment_reference",
    "provider_reference",
    "provider_status",
    "idempotency_key",
    "allocation",
)


def _assert_no_forbidden(text: str) -> None:
    for field in FORBIDDEN:
        assert field not in text, field


def _customer(admin: TestClient, airports: list) -> tuple[TestClient, dict[str, Any]]:
    scenario = iam_support.full_booking_scenario(admin, airports, confirm=True)
    client, _ = iam_support.customer_owner_client(admin, UUID(scenario["customer_id"]))
    return client, scenario


# --------------------------------------------------------------------------- #
# C — /me list isolation, ordering, pagination
# --------------------------------------------------------------------------- #
@requires_db
def test_me_lists_are_tenant_isolated_both_directions(admin: TestClient, airports: list) -> None:
    a_client, a = _customer(admin, airports)
    b_client, b = _customer(admin, airports)

    a_bookings = a_client.get("/api/v1/me/bookings")
    b_bookings = b_client.get("/api/v1/me/bookings")
    assert a_bookings.status_code == 200 and b_bookings.status_code == 200
    a_ids = {row["id"] for row in a_bookings.json()}
    b_ids = {row["id"] for row in b_bookings.json()}
    assert a["booking_id"] in a_ids and b["booking_id"] not in a_ids
    assert b["booking_id"] in b_ids and a["booking_id"] not in b_ids

    # Every list route is tenant-scoped and leaks no confidential field.
    for path in ("/api/v1/me/trip-requests", "/api/v1/me/bookings", "/api/v1/me/payments"):
        a_resp = a_client.get(path)
        assert a_resp.status_code == 200
        _assert_no_forbidden(a_resp.text)


@requires_db
def test_me_lists_empty_and_pagination_bounds(admin: TestClient, airports: list) -> None:
    # A freshly self-provisioned customer with no resources gets safe empty lists.
    fresh = iam_support.new_client()
    iam_support.register_verify_login(fresh)
    for path in ("/api/v1/me/trip-requests", "/api/v1/me/bookings", "/api/v1/me/payments"):
        resp = fresh.get(path)
        assert resp.status_code == 200 and resp.json() == []

    a_client, _ = _customer(admin, airports)
    # Bounded pagination: a limit above the maximum is rejected; a valid limit caps rows.
    assert a_client.get("/api/v1/me/bookings?limit=1000").status_code == 422
    assert a_client.get("/api/v1/me/bookings?limit=0").status_code == 422
    assert len(a_client.get("/api/v1/me/bookings?limit=1").json()) <= 1


@requires_db
def test_platform_and_operator_cannot_use_me_lists_without_customer_context(
    admin: TestClient, airports: list
) -> None:
    scenario = iam_support.full_booking_scenario(admin, airports)
    # A platform product owner has no customer context → 403 on the customer 'my' routes.
    assert admin.get("/api/v1/me/bookings").status_code == 403
    operator, _ = iam_support.operator_role_client(
        UUID(scenario["operator_id"]), iam_support.OrganizationRole.OPERATOR_ADMIN
    )
    assert operator.get("/api/v1/me/bookings").status_code == 403


# --------------------------------------------------------------------------- #
# D/E/F — projections vs. full responses
# --------------------------------------------------------------------------- #
@requires_db
def test_offer_projection_customer_safe_platform_full(admin: TestClient, airports: list) -> None:
    a_client, a = _customer(admin, airports)
    offers = a_client.get(f"/api/v1/trip-requests/{a['trip_id']}/offers")
    assert offers.status_code == 200
    _assert_no_forbidden(offers.text)
    # Platform keeps the full internal response (with the split).
    assert admin.get(f"/api/v1/offers/{a['offer_id']}").json()["platform_fee_minor"] is not None
    # A different customer cannot read this trip's offers.
    other, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    assert other.get(f"/api/v1/trip-requests/{a['trip_id']}/offers").status_code == 404


@requires_db
def test_booking_projection_across_customer_routes(admin: TestClient, airports: list) -> None:
    a_client, a = _customer(admin, airports)
    booking_id, trip_id = a["booking_id"], a["trip_id"]
    for resp in (
        a_client.get(f"/api/v1/bookings/{booking_id}"),
        a_client.get(f"/api/v1/trip-requests/{trip_id}/booking"),
    ):
        assert resp.status_code == 200
        _assert_no_forbidden(resp.text)
        assert resp.json()["id"] == booking_id
    # Operator keeps the full response (a party to the amounts).
    operator, _ = iam_support.operator_role_client(
        UUID(a["operator_id"]), iam_support.OrganizationRole.OPERATOR_ADMIN
    )
    assert operator.get(f"/api/v1/bookings/{booking_id}").json()["platform_fee_minor"] is not None
    # Cross-customer read is concealed.
    other, _ = iam_support.customer_owner_client(admin, iam_support.create_customer(admin))
    assert other.get(f"/api/v1/bookings/{booking_id}").status_code == 404


@requires_db
def test_customer_booking_create_and_cancel_return_safe_view(
    admin: TestClient, airports: list
) -> None:
    # Build a fresh selectable offer for a customer-owned submitted trip.
    scenario = iam_support.full_booking_scenario(admin, airports, confirm=False)
    a_client, _ = iam_support.customer_owner_client(admin, UUID(scenario["customer_id"]))
    # The owning customer cancels its own (pending) booking and receives a safe view.
    cancelled = a_client.post(
        f"/api/v1/bookings/{scenario['booking_id']}/cancel", json={"actor": "CUSTOMER"}
    )
    assert cancelled.status_code == 200
    _assert_no_forbidden(cancelled.text)
    assert cancelled.json()["status"] == "CANCELLED"


@requires_db
def test_payment_status_projection_and_denied_operations(admin: TestClient, airports: list) -> None:
    a_client, a = _customer(admin, airports)
    payment_id, booking_id = a["payment_id"], a["booking_id"]

    for resp in (
        a_client.get(f"/api/v1/payments/{payment_id}"),
        a_client.get(f"/api/v1/bookings/{booking_id}/payment"),
    ):
        assert resp.status_code == 200
        _assert_no_forbidden(resp.text)
        body = resp.json()
        assert "refunded_amount_minor" in body  # aggregate refund status is safe

    # Allocation / refund-list remain denied to the customer (Phase 9.0.A-3 confidential).
    assert a_client.get(f"/api/v1/payments/{payment_id}/allocation").status_code == 403
    assert a_client.get(f"/api/v1/payments/{payment_id}/refunds").status_code == 403
    # Payment operational commands remain denied to the customer.
    body = {"idempotency_key": f"idem-{uuid4().hex}"}
    assert a_client.post(f"/api/v1/payments/{payment_id}/authorize", json=body).status_code == 403
    assert a_client.post(f"/api/v1/payments/{payment_id}/capture", json=body).status_code == 403
    assert a_client.post(f"/api/v1/payments/{payment_id}/void", json=body).status_code == 403
    assert (
        a_client.post(
            f"/api/v1/payments/{payment_id}/refunds",
            json={"idempotency_key": f"idem-{uuid4().hex}", "amount_minor": 100},
        ).status_code
        == 403
    )
    # And a customer can never create an internal payment.
    assert a_client.post(f"/api/v1/bookings/{booking_id}/payment").status_code == 403


# --------------------------------------------------------------------------- #
# G — negative contract on the OpenAPI customer schemas
# --------------------------------------------------------------------------- #
def test_customer_schemas_omit_forbidden_fields_structurally() -> None:
    from sky_bridge_jet.modules.customer_views import (
        CustomerBookingView,
        CustomerOfferView,
        CustomerPaymentStatusView,
    )

    for schema in (CustomerOfferView, CustomerBookingView, CustomerPaymentStatusView):
        fields = set(schema.model_fields)
        assert "operator_amount_minor" not in fields
        assert "platform_fee_minor" not in fields
        assert "provider_payment_reference" not in fields
        assert "idempotency_key" not in fields
