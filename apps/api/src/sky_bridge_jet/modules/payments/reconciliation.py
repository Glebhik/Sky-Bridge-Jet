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
from sky_bridge_jet.modules.payments.domain import PaymentStatus
from sky_bridge_jet.modules.payments.models import Payment


class ProviderPaymentEvent(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    CAPTURED = "CAPTURED"


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
) -> UUID | None:
    """Apply a verified provider payment event; return the payment id if changed."""
    payment = _find_payment(session, provider_reference)
    if payment is None:
        return None

    if event is ProviderPaymentEvent.AUTHORIZED:
        if payment.status is PaymentStatus.CREATED:
            payment.status = PaymentStatus.AUTHORIZED
            payment.authorized_amount_minor = payment.total_amount_minor
            payment.requires_customer_action = False
            payment.authorized_at = _utc_now()
            payment.provider_status = provider_status
            return payment.id
        return None

    if event is ProviderPaymentEvent.AUTHORIZATION_FAILED:
        if payment.status is PaymentStatus.CREATED:
            payment.status = PaymentStatus.AUTHORIZATION_FAILED
            payment.requires_customer_action = False
            payment.provider_status = provider_status
            return payment.id
        return None

    # CAPTURED evidence: only if authorized and the booking is confirmed (the
    # provider never captures on its own authority).
    if payment.status is PaymentStatus.AUTHORIZED:
        booking = session.get(Booking, payment.booking_id)
        if booking is not None and booking.status is BookingStatus.CONFIRMED:
            payment.status = PaymentStatus.CAPTURED
            payment.captured_amount_minor = payment.authorized_amount_minor or 0
            payment.captured_at = _utc_now()
            payment.provider_status = provider_status
            return payment.id
    return None
