from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sky_bridge_jet.modules.bookings.domain import (
    BookingStatus,
    CancellationActor,
    CancellationReason,
    RejectionReason,
)

ShortNote = Annotated[str, Field(min_length=1, max_length=500)]
ConfirmationReference = Annotated[str, Field(min_length=1, max_length=100)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BookingCreate(ApiModel):
    trip_request_id: UUID
    operator_offer_id: UUID


class BookingConfirm(ApiModel):
    # Backward-compatible confirmation only. Authority is always derived from the
    # authenticated principal's active OPERATOR organization.
    operator_id: UUID | None = None
    confirmation_reference: ConfirmationReference | None = None
    note: ShortNote | None = None


class BookingReject(ApiModel):
    operator_id: UUID | None = None
    reason: RejectionReason
    note: ShortNote | None = None


class BookingCancel(ApiModel):
    actor: CancellationActor
    reason: CancellationReason | None = None
    note: ShortNote | None = None


class BookingResponse(ApiModel):
    id: UUID
    reference: str
    trip_request_id: UUID
    operator_offer_id: UUID
    operator_id: UUID
    aircraft_id: UUID
    status: BookingStatus
    currency: str
    operator_amount_minor: int
    platform_fee_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    offer_valid_until: datetime | None
    operator_legal_name: str
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    confirmed_at: datetime | None
    operator_confirmation_reference: str | None
    confirmation_note: str | None
    rejected_at: datetime | None
    rejection_reason: RejectionReason | None
    rejection_note: str | None
    cancelled_at: datetime | None
    cancellation_actor: CancellationActor | None
    cancellation_reason: CancellationReason | None
    cancellation_note: str | None
    created_at: datetime
    updated_at: datetime


class OperatorBookingLegView(ApiModel):
    sequence: int
    origin_airport_code: str
    destination_airport_code: str
    departure_at: datetime
    passenger_count: int


class OperatorBookingView(ApiModel):
    """Minimal operator-safe pending Booking projection (no customer or fee data)."""

    booking_id: UUID
    reference: str
    status: BookingStatus
    trip_request_id: UUID
    operator_offer_id: UUID
    currency: str
    operator_amount_minor: int
    operator_legal_name: str
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    legs: list[OperatorBookingLegView]
    created_at: datetime


class OperatorBookingReadView(ApiModel):
    """Active-operator-safe Booking history/detail projection."""

    id: UUID
    reference: str
    status: BookingStatus
    trip_request_id: UUID
    operator_offer_id: UUID
    aircraft_id: UUID
    currency: str
    operator_amount_minor: int
    operator_legal_name: str
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    legs: list[OperatorBookingLegView]
    confirmed_at: datetime | None
    rejected_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
