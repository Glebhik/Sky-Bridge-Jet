from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from sky_bridge_jet.modules.payments.provider import DECLINE_AUTHORIZATION, DECLINE_CAPTURE

from ._support import (
    authorize,
    authorized_payment,
    booking_scenario,
    capture,
    create_payment,
    new_key,
    refund,
    requires_db,
    void,
)

pytestmark = requires_db


def test_create_payment_snapshots_commercials_and_is_idempotent(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(
        client, airports, operator_amount_minor=1_000_000, tax_amount_minor=50_000
    )
    booking = scenario["booking"]
    payment = create_payment(client, booking["id"])

    assert payment["status"] == "CREATED"
    assert payment["reference"].startswith("PAY-")
    assert payment["currency"] == booking["currency"]
    assert payment["operator_amount_minor"] == 1_000_000
    assert payment["platform_fee_minor"] == booking["platform_fee_minor"]
    assert payment["tax_amount_minor"] == 50_000
    assert payment["total_amount_minor"] == 1_140_000
    assert payment["captured_amount_minor"] == 0
    assert payment["refunded_amount_minor"] == 0

    # Idempotent create returns the same payment.
    again = create_payment(client, booking["id"])
    assert again["id"] == payment["id"]


def test_create_payment_rejected_for_rejected_booking(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    booking = scenario["booking"]
    client.post(
        f"/api/v1/bookings/{booking['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "OTHER"},
    )
    response = client.post(f"/api/v1/bookings/{booking['id']}/payment")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "payment_not_allowed"


def test_authorize_success_and_idempotent_replay(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    key = new_key()

    first = authorize(client, payment["id"], key=key)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "AUTHORIZED"
    assert body["authorized_amount_minor"] == body["total_amount_minor"]
    assert body["authorized_at"] is not None
    assert body["provider_payment_reference"] is not None

    # Replay with the same key returns the same state, no re-authorization.
    replay = authorize(client, payment["id"], key=key)
    assert replay.status_code == 200
    assert replay.json()["provider_payment_reference"] == body["provider_payment_reference"]


def test_authorize_failure_records_failed_state(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    declined = authorize(client, payment["id"], method=DECLINE_AUTHORIZATION)
    assert declined.status_code == 200
    assert declined.json()["status"] == "AUTHORIZATION_FAILED"

    # A fresh attempt (new key, good method) can still succeed.
    ok = authorize(client, payment["id"])
    assert ok.json()["status"] == "AUTHORIZED"


def test_capture_requires_confirmed_booking(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    authorize(client, payment["id"])

    # Booking still pending: capture is refused.
    early = capture(client, payment["id"])
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "payment_not_allowed"

    # Confirm the booking, then capture succeeds.
    client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    captured = capture(client, payment["id"])
    assert captured.status_code == 200, captured.text
    body = captured.json()
    assert body["status"] == "CAPTURED"
    assert body["captured_amount_minor"] == body["total_amount_minor"]
    assert body["captured_at"] is not None


def test_capture_is_idempotent(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = authorized_payment(client, airports)
    key = new_key()
    first = capture(client, scenario["payment"]["id"], key=key)
    assert first.status_code == 200
    replay = capture(client, scenario["payment"]["id"], key=key)
    assert replay.status_code == 200
    assert replay.json()["captured_amount_minor"] == first.json()["captured_amount_minor"]


def test_capture_failure_then_retry(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)  # confirmed
    payment = create_payment(client, scenario["booking"]["id"])
    authorize(client, payment["id"], method=DECLINE_CAPTURE)  # authorizes, capture will fail

    failed = capture(client, payment["id"])
    assert failed.status_code == 200
    assert failed.json()["status"] == "CAPTURE_FAILED"


def test_booking_rejection_after_authorization_blocks_capture_allows_void(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    authorize(client, payment["id"])
    client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "AIRCRAFT_UNAVAILABLE"},
    )

    blocked = capture(client, payment["id"])
    assert blocked.status_code == 409  # booking not confirmed

    released = void(client, payment["id"])
    assert released.status_code == 200
    assert released.json()["status"] == "CANCELLED"


def test_booking_cancellation_after_authorization_blocks_capture(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)  # confirmed + authorized
    client.post(f"/api/v1/bookings/{scenario['booking']['id']}/cancel", json={"actor": "CUSTOMER"})
    blocked = capture(client, scenario["payment"]["id"])
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "payment_not_allowed"


def test_void_after_capture_is_rejected(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = authorized_payment(client, airports)
    capture(client, scenario["payment"]["id"])
    response = void(client, scenario["payment"]["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_payment_state"


def test_refund_partial_then_full(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = scenario["payment"]["id"]
    capture(client, payment_id)
    total = scenario["payment"]["total_amount_minor"]

    partial = refund(client, payment_id, 40_000)
    assert partial.status_code == 201, partial.text
    assert partial.json()["result"] == "SUCCEEDED"
    assert client.get(f"/api/v1/payments/{payment_id}").json()["status"] == "PARTIALLY_REFUNDED"

    rest = refund(client, payment_id, total - 40_000)
    assert rest.status_code == 201
    state = client.get(f"/api/v1/payments/{payment_id}").json()
    assert state["status"] == "REFUNDED"
    assert state["refunded_amount_minor"] == total

    listed = client.get(f"/api/v1/payments/{payment_id}/refunds").json()
    assert len(listed) == 2


def test_over_refund_is_rejected(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = scenario["payment"]["id"]
    capture(client, payment_id)
    total = scenario["payment"]["total_amount_minor"]

    response = refund(client, payment_id, total + 1)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "payment_not_allowed"


def test_refund_before_capture_is_rejected(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    response = refund(client, scenario["payment"]["id"], 1000)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_payment_state"


def test_refund_idempotent_replay(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = scenario["payment"]["id"]
    capture(client, payment_id)
    key = new_key()

    first = refund(client, payment_id, 10_000, key=key)
    assert first.status_code == 201
    replay = refund(client, payment_id, 10_000, key=key)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    # Only one refund actually applied.
    assert client.get(f"/api/v1/payments/{payment_id}").json()["refunded_amount_minor"] == 10_000


def test_idempotency_key_reuse_across_operations_conflicts(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = scenario["payment"]["id"]
    key = new_key()
    # Key first used for capture.
    assert capture(client, payment_id, key=key).status_code == 200
    # Reusing it for a void is a deterministic conflict.
    reused = void(client, payment_id, key=key)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "idempotency_conflict"


def test_allocation_and_settlement_eligibility(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(
        client, airports, operator_amount_minor=1_000_000, tax_amount_minor=50_000
    )
    payment_id = scenario["payment"]["id"]

    before = client.get(f"/api/v1/payments/{payment_id}/allocation").json()
    assert before["settlement_eligibility"] == "NOT_ELIGIBLE"
    assert before["operator_amount_minor"] == 1_000_000
    assert before["platform_fee_minor"] == 90_000
    assert before["tax_amount_minor"] == 50_000
    assert before["total_customer_amount_minor"] == 1_140_000

    capture(client, payment_id)
    after = client.get(f"/api/v1/payments/{payment_id}/allocation").json()
    assert after["settlement_eligibility"] == "ELIGIBLE"
    # A refund removes eligibility (deferred apportionment policy).
    refund(client, payment_id, 1000)
    assert (
        client.get(f"/api/v1/payments/{payment_id}/allocation").json()["settlement_eligibility"]
        == "NOT_ELIGIBLE"
    )
