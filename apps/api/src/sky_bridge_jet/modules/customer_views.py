"""Customer-safe read projections (Phase 9.0.B, ADR-045).

Distinct customer-facing schemas for offers, bookings, and payment status. They are
**structurally** safe: they contain only customer-visible fields, so the internal
operator/platform commercial split, settlement/allocation data, provider references,
raw operations, idempotency keys, and audit metadata can never appear in a customer
response — even in nested objects or lists. Never build these by serializing an
internal schema and deleting keys; always construct the dedicated view.

The full internal ``OperatorOfferResponse`` / ``BookingResponse`` / ``PaymentResponse``
schemas are unchanged and remain the response on operator/platform-audience routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sky_bridge_jet.modules.bookings.domain import (
    BookingStatus,
    CancellationActor,
    CancellationReason,
)
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.offers.domain import EffectiveOfferStatus, effective_offer_status
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.payments.domain import PaymentStatus
from sky_bridge_jet.modules.payments.models import Payment


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Offer
# --------------------------------------------------------------------------- #
class CustomerOfferView(BaseModel):
    """A customer-safe view of an operator offer. No operator/platform split."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trip_request_id: UUID
    status: EffectiveOfferStatus
    currency: str
    total_amount_minor: int  # total customer price
    tax_amount_minor: int  # customer tax
    valid_until: datetime | None
    operator_legal_name: str
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    included_services: str | None
    excluded_services: str | None
    cancellation_policy: str | None
    created_at: datetime
    updated_at: datetime


def customer_offer_view(offer: OperatorOffer) -> CustomerOfferView:
    return CustomerOfferView(
        id=offer.id,
        trip_request_id=offer.trip_request_id,
        status=effective_offer_status(offer.status, offer.valid_until, now=_now()),
        currency=offer.currency,
        total_amount_minor=offer.total_amount_minor,
        tax_amount_minor=offer.tax_amount_minor,
        valid_until=offer.valid_until,
        operator_legal_name=offer.operator_legal_name,
        aircraft_registration=offer.aircraft_registration,
        aircraft_manufacturer=offer.aircraft_manufacturer,
        aircraft_model=offer.aircraft_model,
        aircraft_category=offer.aircraft_category,
        included_services=offer.included_services,
        excluded_services=offer.excluded_services,
        cancellation_policy=offer.cancellation_policy,
        created_at=offer.created_at,
        updated_at=offer.updated_at,
    )


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
class CustomerBookingView(BaseModel):
    """A customer-safe view of a booking. No operator/platform split."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    trip_request_id: UUID
    operator_offer_id: UUID
    status: BookingStatus
    currency: str
    total_amount_minor: int  # total customer price
    tax_amount_minor: int  # customer tax
    operator_legal_name: str
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_actor: CancellationActor | None
    cancellation_reason: CancellationReason | None
    created_at: datetime
    updated_at: datetime


def customer_booking_view(booking: Booking) -> CustomerBookingView:
    return CustomerBookingView(
        id=booking.id,
        reference=booking.reference,
        trip_request_id=booking.trip_request_id,
        operator_offer_id=booking.operator_offer_id,
        status=booking.status,
        currency=booking.currency,
        total_amount_minor=booking.total_amount_minor,
        tax_amount_minor=booking.tax_amount_minor,
        operator_legal_name=booking.operator_legal_name,
        aircraft_registration=booking.aircraft_registration,
        aircraft_manufacturer=booking.aircraft_manufacturer,
        aircraft_model=booking.aircraft_model,
        aircraft_category=booking.aircraft_category,
        confirmed_at=booking.confirmed_at,
        cancelled_at=booking.cancelled_at,
        cancellation_actor=booking.cancellation_actor,
        cancellation_reason=booking.cancellation_reason,
        created_at=booking.created_at,
        updated_at=booking.updated_at,
    )


# --------------------------------------------------------------------------- #
# Payment status
# --------------------------------------------------------------------------- #
class CustomerPaymentStatusView(BaseModel):
    """A customer-safe payment-status view (status only, never operations).

    Refund visibility is the aggregate ``refunded_amount_minor`` — never the raw
    refund list or allocation. No provider references, no idempotency keys.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    booking_id: UUID
    status: PaymentStatus
    currency: str
    total_amount_minor: int  # total customer price
    authorized_amount_minor: int | None
    captured_amount_minor: int
    refunded_amount_minor: int  # aggregate refunded to the customer
    requires_customer_action: bool
    authorized_at: datetime | None
    captured_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


def customer_payment_view(payment: Payment) -> CustomerPaymentStatusView:
    return CustomerPaymentStatusView(
        id=payment.id,
        booking_id=payment.booking_id,
        status=payment.status,
        currency=payment.currency,
        total_amount_minor=payment.total_amount_minor,
        authorized_amount_minor=payment.authorized_amount_minor,
        captured_amount_minor=payment.captured_amount_minor,
        refunded_amount_minor=payment.refunded_amount_minor,
        requires_customer_action=payment.requires_customer_action,
        authorized_at=payment.authorized_at,
        captured_at=payment.captured_at,
        cancelled_at=payment.cancelled_at,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )
