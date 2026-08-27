from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.domain import BookingConflictError, BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.schemas import BookingConfirm, BookingReject
from sky_bridge_jet.modules.bookings.services import BookingService
from sky_bridge_jet.modules.payments.domain import (
    PaymentConflictError,
    PaymentOperationResult,
    PaymentOperationType,
    PaymentProviderKind,
    PaymentStatus,
)
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.provider import (
    DECLINE_CAPTURE,
    DECLINE_CAPTURE_AND_VOID,
    DECLINE_VOID,
    ProviderOutcome,
    ProviderResult,
)
from sky_bridge_jet.modules.payments.schemas import PaymentCapture, PaymentVoid
from sky_bridge_jet.modules.payments.services import PaymentService

from ._support import authorize, booking_scenario, capture, create_payment, requires_db

pytestmark = requires_db


def _suspend_operator(client: TestClient, operator_id: str) -> None:
    response = client.post(
        f"/api/v1/operators/{operator_id}/admission/review",
        json={
            "action": "SUSPEND",
            "actor_type": "PLATFORM_REVIEWER",
            "reason_code": "MANUAL_SUSPENSION",
        },
    )
    assert response.status_code == 200


def _payment(booking_id: str) -> Payment | None:
    with SessionLocal() as session:
        return session.scalar(select(Payment).where(Payment.booking_id == UUID(booking_id)))


def _operations(payment_id: UUID) -> list[PaymentOperation]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(PaymentOperation)
                .where(PaymentOperation.payment_id == payment_id)
                .order_by(PaymentOperation.created_at, PaymentOperation.id)
            )
        )


def _authorized_pending(
    client: TestClient, airports: list[dict[str, Any]], *, method: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    response = authorize(client, payment["id"], method=method)
    assert response.status_code == 200
    assert response.json()["status"] == "AUTHORIZED"
    return scenario, response.json()


def _capture_failed(
    client: TestClient,
    airports: list[dict[str, Any]],
    *,
    fail_void: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    scenario = booking_scenario(client, airports)
    payment = create_payment(client, scenario["booking"]["id"])
    method = DECLINE_CAPTURE_AND_VOID if fail_void else DECLINE_CAPTURE
    authorized = authorize(client, payment["id"], method=method).json()
    failed = capture(client, payment["id"])
    assert failed.status_code == 200
    assert failed.json()["status"] == "CAPTURE_FAILED"
    reference = failed.json()["provider_payment_reference"]
    assert reference is not None
    return scenario, authorized, reference


class _VoidSpy:
    kind = PaymentProviderKind.FAKE

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def void(self, *, provider_reference: str, idempotency_key: str) -> ProviderResult:
        self.calls.append((provider_reference, idempotency_key))
        if self.fail:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=provider_reference,
                failure_code="void_declined",
            )
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_reference=provider_reference.replace("fauth", "fvoid", 1),
        )


def test_confirm_captures_authorized_payment_once(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario, authorized = _authorized_pending(client, airports)
    booking_id = scenario["booking"]["id"]
    response = client.post(
        f"/api/v1/bookings/{booking_id}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 200
    payment = _payment(booking_id)
    assert payment is not None
    assert payment.status is PaymentStatus.CAPTURED
    assert payment.captured_amount_minor == payment.total_amount_minor
    assert payment.refunded_amount_minor == 0
    operations = _operations(UUID(authorized["id"]))
    assert [item.operation for item in operations] == [
        PaymentOperationType.AUTHORIZE,
        PaymentOperationType.CAPTURE,
    ]
    assert all(item.result is PaymentOperationResult.SUCCEEDED for item in operations)


@pytest.mark.parametrize("decision", ["reject", "cancel"])
def test_reject_or_cancel_voids_authorized_payment(
    client: TestClient, airports: list[dict[str, Any]], decision: str
) -> None:
    scenario, authorized = _authorized_pending(client, airports)
    booking_id = scenario["booking"]["id"]
    body = (
        {"operator_id": scenario["operator"]["id"], "reason": "OTHER"}
        if decision == "reject"
        else {"actor": "CUSTOMER"}
    )
    response = client.post(f"/api/v1/bookings/{booking_id}/{decision}", json=body)
    assert response.status_code == 200
    payment = _payment(booking_id)
    assert payment is not None
    assert payment.status is PaymentStatus.CANCELLED
    assert payment.captured_amount_minor == payment.refunded_amount_minor == 0
    assert [item.operation for item in _operations(UUID(authorized["id"]))] == [
        PaymentOperationType.AUTHORIZE,
        PaymentOperationType.VOID,
    ]


@pytest.mark.parametrize("decision", ["confirm", "reject", "cancel"])
def test_booking_decision_without_payment_never_creates_one(
    client: TestClient, airports: list[dict[str, Any]], decision: str
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    booking_id = scenario["booking"]["id"]
    body = (
        {"operator_id": scenario["operator"]["id"]}
        if decision == "confirm"
        else {"operator_id": scenario["operator"]["id"], "reason": "OTHER"}
        if decision == "reject"
        else {"actor": "CUSTOMER"}
    )
    assert client.post(f"/api/v1/bookings/{booking_id}/{decision}", json=body).status_code == 200
    assert _payment(booking_id) is None


def test_cancel_captured_payment_does_not_refund(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    payment = create_payment(client, scenario["booking"]["id"])
    assert authorize(client, payment["id"]).status_code == 200
    assert capture(client, payment["id"]).status_code == 200
    assert (
        client.post(
            f"/api/v1/bookings/{scenario['booking']['id']}/cancel", json={"actor": "CUSTOMER"}
        ).status_code
        == 200
    )
    final = _payment(scenario["booking"]["id"])
    assert final is not None
    assert final.status is PaymentStatus.CAPTURED
    assert final.refunded_amount_minor == 0
    assert PaymentOperationType.REFUND not in {
        item.operation for item in _operations(UUID(payment["id"]))
    }


def test_capture_failure_is_factual_and_does_not_claim_captured(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario, authorized = _authorized_pending(client, airports, method=DECLINE_CAPTURE)
    response = client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 200
    payment = _payment(scenario["booking"]["id"])
    assert payment is not None
    assert payment.status is PaymentStatus.CAPTURE_FAILED
    assert payment.captured_amount_minor == 0
    assert _operations(UUID(authorized["id"]))[-1].result is PaymentOperationResult.FAILED


def test_void_failure_leaves_authorization_and_records_failure(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario, authorized = _authorized_pending(client, airports, method=DECLINE_VOID)
    response = client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "OTHER"},
    )
    assert response.status_code == 200
    payment = _payment(scenario["booking"]["id"])
    assert payment is not None
    assert payment.status is PaymentStatus.AUTHORIZED
    operation = _operations(UUID(authorized["id"]))[-1]
    assert operation.operation is PaymentOperationType.VOID
    assert operation.result is PaymentOperationResult.FAILED


@pytest.mark.parametrize("provider_fails", [False, True])
def test_direct_capture_failed_void_contacts_provider_and_is_truthful(
    client: TestClient,
    airports: list[dict[str, Any]],
    provider_fails: bool,
) -> None:
    scenario, authorized, reference = _capture_failed(client, airports)
    key = f"direct-capture-failed-void-{authorized['id']}"
    spy = _VoidSpy(fail=provider_fails)
    with SessionLocal() as session:
        result = PaymentService(session, provider=spy).void(  # type: ignore[arg-type]
            UUID(authorized["id"]), PaymentVoid(idempotency_key=key)
        )
        expected = PaymentStatus.CAPTURE_FAILED if provider_fails else PaymentStatus.CANCELLED
        assert result.status is expected
        if provider_fails:
            assert result.cancelled_at is None
        else:
            assert result.cancelled_at is not None
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == reference
    UUID(spy.calls[0][1])
    operations = _operations(UUID(authorized["id"]))
    voids = [item for item in operations if item.operation is PaymentOperationType.VOID]
    assert len(voids) == 1
    assert voids[0].result is (
        PaymentOperationResult.FAILED if provider_fails else PaymentOperationResult.SUCCEEDED
    )
    final = _payment(scenario["booking"]["id"])
    assert final is not None
    if provider_fails:
        assert final.status is PaymentStatus.CAPTURE_FAILED
        assert final.cancelled_at is None
        assert final.provider_payment_reference == reference
    else:
        assert final.status is PaymentStatus.CANCELLED
        assert final.cancelled_at is not None
        assert final.provider_payment_reference == reference
    assert final.refunded_amount_minor == 0


def test_direct_capture_failed_void_replay_does_not_call_provider_twice(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    _, authorized, reference = _capture_failed(client, airports)
    key = f"direct-replay-{authorized['id']}"
    spy = _VoidSpy()
    with SessionLocal() as session:
        service = PaymentService(session, provider=spy)  # type: ignore[arg-type]
        service.void(UUID(authorized["id"]), PaymentVoid(idempotency_key=key))
    with SessionLocal() as session:
        PaymentService(session, provider=spy).void(  # type: ignore[arg-type]
            UUID(authorized["id"]), PaymentVoid(idempotency_key=key)
        )
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == reference
    UUID(spy.calls[0][1])
    assert (
        len(
            [
                item
                for item in _operations(UUID(authorized["id"]))
                if item.operation is PaymentOperationType.VOID
            ]
        )
        == 1
    )


@pytest.mark.parametrize("decision", ["reject", "cancel"])
@pytest.mark.parametrize("provider_fails", [False, True])
def test_capture_failed_booking_orchestration_voids_truthfully(
    client: TestClient,
    airports: list[dict[str, Any]],
    decision: str,
    provider_fails: bool,
) -> None:
    scenario, authorized, reference = _capture_failed(client, airports, fail_void=provider_fails)
    booking_id = scenario["booking"]["id"]
    if decision == "reject":
        # Safe synthetic anomaly requested by the audit: a pending Booking whose
        # retained authorization already has a failed capture attempt.
        with SessionLocal.begin() as session:
            booking = session.get(Booking, UUID(booking_id))
            assert booking is not None
            booking.status = BookingStatus.PENDING_OPERATOR_CONFIRMATION
            booking.confirmed_at = None
        body = {"operator_id": scenario["operator"]["id"], "reason": "OTHER"}
    else:
        body = {"actor": "CUSTOMER"}
    response = client.post(f"/api/v1/bookings/{booking_id}/{decision}", json=body)
    assert response.status_code == 200
    final = _payment(booking_id)
    assert final is not None
    assert final.status is (
        PaymentStatus.CAPTURE_FAILED if provider_fails else PaymentStatus.CANCELLED
    )
    if provider_fails:
        assert final.cancelled_at is None
    else:
        assert final.cancelled_at is not None
    assert final.provider_payment_reference == reference
    voids = [
        item
        for item in _operations(UUID(authorized["id"]))
        if item.operation is PaymentOperationType.VOID
    ]
    assert len(voids) == 1
    assert voids[0].result is (
        PaymentOperationResult.FAILED if provider_fails else PaymentOperationResult.SUCCEEDED
    )
    assert final.refunded_amount_minor == 0


@pytest.mark.parametrize("initial_status", ["CREATED", "AUTHORIZATION_FAILED"])
def test_confirm_does_not_capture_ineligible_precapture_state(
    client: TestClient, airports: list[dict[str, Any]], initial_status: str
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    if initial_status == "AUTHORIZATION_FAILED":
        assert (
            authorize(client, payment["id"], method="decline-authorization").json()["status"]
            == initial_status
        )
    response = client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 200
    final = _payment(scenario["booking"]["id"])
    assert final is not None and final.status.value == initial_status
    assert PaymentOperationType.CAPTURE not in {
        operation.operation for operation in _operations(UUID(payment["id"]))
    }


def test_compliance_lapse_prevents_booking_mutation_and_capture(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario, authorized = _authorized_pending(client, airports)
    _suspend_operator(client, scenario["operator"]["id"])
    response = client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 409
    payment = _payment(scenario["booking"]["id"])
    assert payment is not None
    assert payment.status is PaymentStatus.AUTHORIZED
    assert payment.captured_amount_minor == 0
    assert [operation.operation for operation in _operations(UUID(authorized["id"]))] == [
        PaymentOperationType.AUTHORIZE
    ]


def test_concurrent_confirm_reject_keeps_booking_and_payment_consistent(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario, authorized = _authorized_pending(client, airports)
    booking_id = UUID(scenario["booking"]["id"])
    operator_id = UUID(scenario["operator"]["id"])
    barrier = threading.Barrier(2)

    def confirm() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).confirm(booking_id, BookingConfirm(operator_id=operator_id))
        except BookingConflictError:
            pass

    def reject() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).reject(
                    booking_id, BookingReject(operator_id=operator_id, reason="OTHER")
                )
        except BookingConflictError:
            pass

    threads = [threading.Thread(target=confirm), threading.Thread(target=reject)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with SessionLocal() as session:
        booking = session.get(Booking, booking_id)
        payment = session.get(Payment, UUID(authorized["id"]))
        assert booking is not None and payment is not None
        assert (booking.status, payment.status) in {
            (BookingStatus.CONFIRMED, PaymentStatus.CAPTURED),
            (BookingStatus.REJECTED, PaymentStatus.CANCELLED),
        }
    financial = [
        operation.operation
        for operation in _operations(UUID(authorized["id"]))
        if operation.operation is not PaymentOperationType.AUTHORIZE
    ]
    assert financial in [[PaymentOperationType.CAPTURE], [PaymentOperationType.VOID]]


def test_capture_void_race_has_one_financial_winner(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    payment = create_payment(client, scenario["booking"]["id"])
    authorized = authorize(client, payment["id"]).json()
    payment_id = UUID(authorized["id"])
    barrier = threading.Barrier(2)

    def run_capture() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).capture(
                    payment_id, PaymentCapture(idempotency_key=f"race-capture-{payment_id}")
                )
        except PaymentConflictError:
            pass

    def run_void() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).void(
                    payment_id, PaymentVoid(idempotency_key=f"race-void-{payment_id}")
                )
        except PaymentConflictError:
            pass

    threads = [threading.Thread(target=run_capture), threading.Thread(target=run_void)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    final = _payment(scenario["booking"]["id"])
    assert final is not None
    assert final.status in {PaymentStatus.CAPTURED, PaymentStatus.CANCELLED}
    financial = [
        operation.operation
        for operation in _operations(payment_id)
        if operation.operation is not PaymentOperationType.AUTHORIZE
    ]
    assert financial in [[PaymentOperationType.CAPTURE], [PaymentOperationType.VOID]]
