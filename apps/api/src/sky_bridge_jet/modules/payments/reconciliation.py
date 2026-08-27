"""Apply verified provider events to the Payment aggregate.

These helpers run inside the caller's transaction (the webhook reconciliation
service owns the transaction), so they never open their own. A provider event is
treated as evidence: only allowed domain transitions are applied, out-of-order or
duplicate events are ignored idempotently, and capture still requires a confirmed
booking — the domain, not the provider, remains authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.payments.domain import (
    PaymentOperationResult,
    PaymentOperationType,
    PaymentStatus,
)
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation


class ProviderPaymentEvent(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    CAPTURED = "CAPTURED"
    CANCELLED = "CANCELLED"


_OPERATION_FOR_EVENT = {
    ProviderPaymentEvent.AUTHORIZED: PaymentOperationType.AUTHORIZE,
    ProviderPaymentEvent.AUTHORIZATION_FAILED: PaymentOperationType.AUTHORIZE,
    ProviderPaymentEvent.CAPTURED: PaymentOperationType.CAPTURE,
    ProviderPaymentEvent.CANCELLED: PaymentOperationType.VOID,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _find_payment(session: Session, provider_reference: str) -> Payment | None:
    return session.scalar(
        select(Payment)
        .where(Payment.provider_payment_reference == provider_reference)
        .with_for_update()
    )


def apply_provider_payment_event(
    session: Session,
    *,
    provider_reference: str,
    event: ProviderPaymentEvent,
    provider_status: str | None = None,
    operation_correlation: str | None = None,
) -> UUID | None:
    """Apply a verified provider payment event; return the payment id if changed."""
    payment = _find_payment(session, provider_reference)
    operation: PaymentOperation | None = None
    if operation_correlation is not None:
        try:
            correlation_id = UUID(
                operation_correlation.removeprefix("authorize:")
                .removeprefix("capture:")
                .removeprefix("void:")
            )
        except ValueError:
            return None
        operation = session.scalar(
            select(PaymentOperation)
            .where(PaymentOperation.correlation_id == correlation_id)
            .with_for_update()
        )
        if operation is None:
            return None
        if payment is not None and operation.payment_id != payment.id:
            # Both identifiers are provider evidence for one financial resource.
            # Never choose one and ignore a conflicting binding: doing so could
            # mutate one Payment while completing another Payment's operation.
            return None
        if operation.operation is not _OPERATION_FOR_EVENT[event]:
            # A correlation is evidence for a particular operation, not merely
            # a way to locate its Payment. Reject incompatible event/operation
            # pairs before binding a reference or mutating financial state.
            return None
        if payment is None:
            payment = session.get(Payment, operation.payment_id, with_for_update=True)
    if payment is None:
        return None
    if payment.provider_payment_reference is None:
        payment.provider_payment_reference = provider_reference

    if event is ProviderPaymentEvent.AUTHORIZED:
        if payment.status is PaymentStatus.CREATED:
            payment.status = PaymentStatus.AUTHORIZED
            payment.authorized_amount_minor = payment.total_amount_minor
            payment.requires_customer_action = False
            payment.authorized_at = _utc_now()
            payment.provider_status = provider_status
            _complete_operation(operation, PaymentOperationType.AUTHORIZE, succeeded=True)
            return payment.id
        return None

    if event is ProviderPaymentEvent.AUTHORIZATION_FAILED:
        if payment.status is PaymentStatus.CREATED:
            payment.status = PaymentStatus.AUTHORIZATION_FAILED
            payment.requires_customer_action = False
            payment.provider_status = provider_status
            _complete_operation(operation, PaymentOperationType.AUTHORIZE, succeeded=False)
            return payment.id
        return None

    # CAPTURED evidence: only if authorized and the booking is confirmed (the
    # provider never captures on its own authority).
    if event is ProviderPaymentEvent.CAPTURED and payment.status is PaymentStatus.AUTHORIZED:
        booking = session.get(Booking, payment.booking_id)
        if booking is not None and booking.status is BookingStatus.CONFIRMED:
            payment.status = PaymentStatus.CAPTURED
            payment.captured_amount_minor = payment.authorized_amount_minor or 0
            payment.captured_at = _utc_now()
            payment.provider_status = provider_status
            _complete_operation(operation, PaymentOperationType.CAPTURE, succeeded=True)
            return payment.id
    if event is ProviderPaymentEvent.CANCELLED and payment.status in {
        PaymentStatus.CREATED,
        PaymentStatus.AUTHORIZATION_FAILED,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.CAPTURE_FAILED,
    }:
        payment.status = PaymentStatus.CANCELLED
        payment.cancelled_at = _utc_now()
        payment.requires_customer_action = False
        payment.provider_status = provider_status
        _complete_operation(operation, PaymentOperationType.VOID, succeeded=True)
        return payment.id
    return None


def _complete_operation(
    operation: PaymentOperation | None,
    expected: PaymentOperationType,
    *,
    succeeded: bool,
) -> None:
    if operation is None or operation.operation is not expected:
        return
    if operation.result not in {PaymentOperationResult.PENDING, PaymentOperationResult.UNKNOWN}:
        return
    operation.result = (
        PaymentOperationResult.SUCCEEDED if succeeded else PaymentOperationResult.FAILED
    )
    operation.failure_code = None if succeeded else "provider_authorization_failed"
