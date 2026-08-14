"""Phase 9.0.A-2 (I) — operator response confidentiality.

The owning operator is a legitimate party to its own offer/booking commercial amounts
(it authors the offer; the platform fee is derivable from the totals it sets), so it
receives the existing response. Confidentiality is enforced by ownership + 404
concealment: another operator never receives a body containing the commercial split.
"""

from __future__ import annotations

import os
from uuid import UUID

import iam_support
import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.modules.iam.domain import OrganizationRole

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_FORBIDDEN = ("platform_fee_minor", "operator_amount_minor", "total_amount_minor")


@requires_db
def test_cross_operator_offer_and_booking_reads_leak_nothing(
    admin: TestClient, airports: list
) -> None:
    b = iam_support.full_booking_scenario(admin, airports, confirm=True)
    a_client, _ = iam_support.operator_role_client(
        UUID(str(iam_support.create_operator(admin))), OrganizationRole.OPERATOR_ADMIN
    )

    offer = a_client.get(f"/api/v1/offers/{b['offer_id']}")
    assert offer.status_code == 404
    booking = a_client.get(f"/api/v1/bookings/{b['booking_id']}")
    assert booking.status_code == 404
    for field in _FORBIDDEN:
        assert field not in offer.text
        assert field not in booking.text


@requires_db
def test_owning_operator_receives_its_own_offer_and_booking(
    admin: TestClient, airports: list
) -> None:
    s = iam_support.full_booking_scenario(admin, airports, confirm=True)
    op_client, _ = iam_support.operator_role_client(
        UUID(s["operator_id"]), OrganizationRole.OPERATOR_ADMIN
    )
    offer = op_client.get(f"/api/v1/offers/{s['offer_id']}")
    assert offer.status_code == 200
    assert offer.json()["operator_id"] == s["operator_id"]
    booking = op_client.get(f"/api/v1/bookings/{s['booking_id']}")
    assert booking.status_code == 200
    assert booking.json()["operator_id"] == s["operator_id"]
