"""Adversarial binding tests for provider references and durable correlations."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.payments.domain import (
    PaymentOperationResult,
    PaymentOperationType,
    PaymentProviderKind,
    PaymentStatus,
)
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.reconciliation import (
    ProviderPaymentEvent,
    apply_provider_payment_event,
)
from sky_bridge_jet.modules.payments.services import PaymentService

from ._support import authorized_payment, booking_scenario, requires_db


def _created_payment(client: TestClient, airports: list[dict[str, Any]]) -> UUID:
    booking = booking_scenario(client, airports, confirm=False)["booking"]
    with SessionLocal() as session:
        return PaymentService(session).create_for_booking(UUID(booking["id"])).id


def _target_payment(
    client: TestClient,
    airports: list[dict[str, Any]],
    *,
    authorized: bool,
) -> UUID:
    if authorized:
        return UUID(authorized_payment(client, airports)["payment"]["id"])
    return _created_payment(client, airports)


def _operation(payment_id: UUID, operation: PaymentOperationType) -> tuple[UUID, UUID]:
    with SessionLocal.begin() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        row = PaymentOperation(
            payment_id=payment_id,
            operation=operation,
            result=PaymentOperationResult.UNKNOWN,
            idempotency_key=f"binding-{uuid4()}",
            amount_minor=payment.authorized_amount_minor or payment.total_amount_minor,
            provider_reference=payment.provider_payment_reference,
            provider_kind=PaymentProviderKind.FAKE,
            attempt_count=1,
        )
        session.add(row)
        session.flush()
        return row.id, row.correlation_id


def _ensure_reference(payment_id: UUID) -> str:
    with SessionLocal.begin() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        if payment.provider_payment_reference is None:
            payment.provider_payment_reference = f"pi_binding_{uuid4().hex}"
        return payment.provider_payment_reference


def _snapshot(payment_ids: tuple[UUID, UUID], operation_id: UUID) -> tuple[Any, ...]:
    with SessionLocal() as session:
        payments = [session.get(Payment, payment_id) for payment_id in payment_ids]
        assert all(payment is not None for payment in payments)
        operation = session.get(PaymentOperation, operation_id)
        assert operation is not None
        bookings = [session.get(Booking, payment.booking_id) for payment in payments if payment]
        return (
            tuple(
                (
                    payment.status,
                    payment.authorized_amount_minor,
                    payment.captured_amount_minor,
                    payment.refunded_amount_minor,
                    payment.provider_payment_reference,
                    payment.requires_customer_action,
                )
                for payment in payments
                if payment
            ),
            operation.result,
            operation.provider_reference,
            tuple(booking.status for booking in bookings if booking),
        )


@requires_db
@pytest.mark.parametrize(
    ("event", "operation", "target_authorized"),
    [
        (ProviderPaymentEvent.AUTHORIZED, PaymentOperationType.AUTHORIZE, False),
        (ProviderPaymentEvent.CAPTURED, PaymentOperationType.CAPTURE, True),
        (ProviderPaymentEvent.CANCELLED, PaymentOperationType.VOID, True),
    ],
)
def test_mismatched_reference_and_correlation_fail_closed_before_any_mutation(
    client: TestClient,
    airports: list[dict[str, Any]],
    event: ProviderPaymentEvent,
    operation: PaymentOperationType,
    target_authorized: bool,
) -> None:
    payment_a = _created_payment(client, airports)
    payment_b = _target_payment(client, airports, authorized=target_authorized)
    operation_a, correlation_a = _operation(payment_a, operation)
    reference_b = _ensure_reference(payment_b)
    before = _snapshot((payment_a, payment_b), operation_a)

    with SessionLocal.begin() as session:
        changed = apply_provider_payment_event(
            session,
            provider_reference=reference_b,
            operation_correlation=str(correlation_a),
            event=event,
            provider_status="adversarial-mismatch",
        )
        assert changed is None

    assert _snapshot((payment_a, payment_b), operation_a) == before


@requires_db
@pytest.mark.parametrize(
    ("event", "operation", "target_authorized", "expected_status", "expected_result"),
    [
        (
            ProviderPaymentEvent.AUTHORIZED,
            PaymentOperationType.AUTHORIZE,
            False,
            PaymentStatus.AUTHORIZED,
            PaymentOperationResult.SUCCEEDED,
        ),
        (
            ProviderPaymentEvent.AUTHORIZATION_FAILED,
            PaymentOperationType.AUTHORIZE,
            False,
            PaymentStatus.AUTHORIZATION_FAILED,
            PaymentOperationResult.FAILED,
        ),
        (
            ProviderPaymentEvent.CAPTURED,
            PaymentOperationType.CAPTURE,
            True,
            PaymentStatus.CAPTURED,
            PaymentOperationResult.SUCCEEDED,
        ),
        (
            ProviderPaymentEvent.CANCELLED,
            PaymentOperationType.VOID,
            True,
            PaymentStatus.CANCELLED,
            PaymentOperationResult.SUCCEEDED,
        ),
    ],
)
def test_matched_reference_and_correlation_reconcile_the_same_payment(
    client: TestClient,
    airports: list[dict[str, Any]],
    event: ProviderPaymentEvent,
    operation: PaymentOperationType,
    target_authorized: bool,
    expected_status: PaymentStatus,
    expected_result: PaymentOperationResult,
) -> None:
    payment_id = _target_payment(client, airports, authorized=target_authorized)
    operation_id, correlation = _operation(payment_id, operation)
    reference = _ensure_reference(payment_id)

    with SessionLocal.begin() as session:
        changed = apply_provider_payment_event(
            session,
            provider_reference=reference,
            operation_correlation=str(correlation),
            event=event,
            provider_status="matched",
        )
        assert changed == payment_id

    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
        row = session.get(PaymentOperation, operation_id)
        assert payment is not None and row is not None
        assert payment.status is expected_status
        assert row.result is expected_result
        if event is ProviderPaymentEvent.CAPTURED:
            assert payment.captured_amount_minor == payment.authorized_amount_minor
        if event is ProviderPaymentEvent.CANCELLED:
            assert payment.captured_amount_minor == 0
            assert payment.refunded_amount_minor == 0


@requires_db
def test_known_reference_with_unknown_or_malformed_correlation_fails_closed(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    payment_id = _created_payment(client, airports)
    reference = _ensure_reference(payment_id)
    for correlation in (str(uuid4()), "not-a-correlation"):
        with SessionLocal.begin() as session:
            changed = apply_provider_payment_event(
                session,
                provider_reference=reference,
                operation_correlation=correlation,
                event=ProviderPaymentEvent.AUTHORIZED,
            )
            assert changed is None
    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        assert payment.status is PaymentStatus.CREATED


@requires_db
def test_unknown_reference_recovers_only_the_correlated_operation_payment(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    payment_id = _created_payment(client, airports)
    operation_id, correlation = _operation(payment_id, PaymentOperationType.AUTHORIZE)
    recovered_reference = f"pi_recovered_{uuid4().hex}"

    with SessionLocal.begin() as session:
        changed = apply_provider_payment_event(
            session,
            provider_reference=recovered_reference,
            operation_correlation=str(correlation),
            event=ProviderPaymentEvent.AUTHORIZED,
        )
        assert changed == payment_id

    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
        operation = session.get(PaymentOperation, operation_id)
        assert payment is not None and operation is not None
        assert payment.status is PaymentStatus.AUTHORIZED
        assert payment.provider_payment_reference == recovered_reference
        assert operation.result is PaymentOperationResult.SUCCEEDED


@requires_db
def test_mismatched_out_of_order_event_cannot_regress_or_complete_foreign_operation(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    payment_a = _created_payment(client, airports)
    operation_a, correlation_a = _operation(payment_a, PaymentOperationType.AUTHORIZE)
    payment_b = _target_payment(client, airports, authorized=True)
    reference_b = _ensure_reference(payment_b)
    before = _snapshot((payment_a, payment_b), operation_a)

    with SessionLocal.begin() as session:
        changed = apply_provider_payment_event(
            session,
            provider_reference=reference_b,
            operation_correlation=str(correlation_a),
            event=ProviderPaymentEvent.AUTHORIZED,
        )
        assert changed is None

    assert _snapshot((payment_a, payment_b), operation_a) == before


@requires_db
@pytest.mark.parametrize(
    ("event", "operation", "target_authorized"),
    [
        (ProviderPaymentEvent.CANCELLED, PaymentOperationType.CAPTURE, True),
        (ProviderPaymentEvent.CAPTURED, PaymentOperationType.VOID, True),
        (ProviderPaymentEvent.CANCELLED, PaymentOperationType.AUTHORIZE, True),
        (ProviderPaymentEvent.CAPTURED, PaymentOperationType.AUTHORIZE, True),
        (ProviderPaymentEvent.AUTHORIZED, PaymentOperationType.CAPTURE, False),
        (ProviderPaymentEvent.AUTHORIZED, PaymentOperationType.VOID, False),
        (ProviderPaymentEvent.AUTHORIZATION_FAILED, PaymentOperationType.CAPTURE, False),
        (ProviderPaymentEvent.AUTHORIZATION_FAILED, PaymentOperationType.VOID, False),
    ],
)
def test_event_and_correlated_operation_type_must_agree(
    client: TestClient,
    airports: list[dict[str, Any]],
    event: ProviderPaymentEvent,
    operation: PaymentOperationType,
    target_authorized: bool,
) -> None:
    payment_id = _target_payment(client, airports, authorized=target_authorized)
    operation_id, correlation = _operation(payment_id, operation)
    reference = _ensure_reference(payment_id)
    before = _snapshot((payment_id, payment_id), operation_id)

    with SessionLocal.begin() as session:
        changed = apply_provider_payment_event(
            session,
            provider_reference=reference,
            operation_correlation=str(correlation),
            event=event,
            provider_status="wrong-event-operation-pair",
        )
        assert changed is None

    assert _snapshot((payment_id, payment_id), operation_id) == before
