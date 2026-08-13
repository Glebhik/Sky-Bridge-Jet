from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.bookings.domain import (
    BookingEligibilityError,
    BookingStatus,
    OperatorMismatchError,
    generate_booking_reference,
    is_offer_within_validity,
    validate_booking_transition,
)
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.repositories import BookingRepository
from sky_bridge_jet.modules.bookings.schemas import (
    BookingCancel,
    BookingConfirm,
    BookingCreate,
    BookingReject,
)
from sky_bridge_jet.modules.compliance.domain import ComplianceGateError
from sky_bridge_jet.modules.compliance.evaluator import ComplianceEvaluator
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError, TripRequestStatus
from sky_bridge_jet.modules.core_aviation.models import TripRequest
from sky_bridge_jet.modules.core_aviation.repositories import TripRequestRepository
from sky_bridge_jet.modules.offers.domain import OfferStatus, validate_price_consistency
from sky_bridge_jet.modules.offers.repositories import OperatorOfferRepository


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


# Optional audit hook run inside the command transaction (Phase 9.0.A-1).
OnCommit = Callable[[Session], None] | None


class BookingService:
    """Own booking-workflow use cases within one explicit transaction per write.

    Authorization is intentionally deferred for Phase 4. The commands are scoped
    by actor role so future authorization can wrap them without a redesign:
    creating a booking is a customer/platform action; confirmation and rejection
    are operator actions (verified against the booking's operator); cancellation
    records the initiating actor explicitly.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.bookings = BookingRepository(session)
        self.offers = OperatorOfferRepository(session)
        self.trips = TripRequestRepository(session)

    # -- Customer / platform action -----------------------------------------

    def create(self, data: BookingCreate, *, on_commit: OnCommit = None) -> Booking:
        with self.session.begin():
            # Lock the trip row so concurrent creations for the same trip
            # serialize; the partial unique index is the ultimate backstop.
            trip = self.session.get(TripRequest, data.trip_request_id, with_for_update=True)
            if trip is None:
                raise _not_found("Trip request")
            if trip.status is not TripRequestStatus.SUBMITTED:
                raise BookingEligibilityError("Trip request is not eligible for booking")

            offer = self.offers.get_for_update(data.operator_offer_id)
            if offer is None or offer.trip_request_id != data.trip_request_id:
                raise _not_found("Operator offer")
            if offer.status is not OfferStatus.SELECTED:
                raise BookingEligibilityError("A booking requires a selected offer")
            if not is_offer_within_validity(offer.valid_until, now=_utc_now()):
                raise BookingEligibilityError("The selected offer has expired")

            if self.bookings.get_active_for_trip(data.trip_request_id) is not None:
                raise BookingEligibilityError(
                    "An active booking already exists for this trip request"
                )

            # Defensive: the snapshot must satisfy the same integrity as the offer.
            validate_price_consistency(
                operator_amount_minor=offer.operator_amount_minor,
                platform_fee_minor=offer.platform_fee_minor,
                tax_amount_minor=offer.tax_amount_minor,
                total_amount_minor=offer.total_amount_minor,
            )

            booking = self.bookings.add(
                Booking(
                    reference=generate_booking_reference(),
                    trip_request_id=offer.trip_request_id,
                    operator_offer_id=offer.id,
                    operator_id=offer.operator_id,
                    aircraft_id=offer.aircraft_id,
                    status=BookingStatus.PENDING_OPERATOR_CONFIRMATION,
                    currency=offer.currency,
                    operator_amount_minor=offer.operator_amount_minor,
                    platform_fee_minor=offer.platform_fee_minor,
                    tax_amount_minor=offer.tax_amount_minor,
                    total_amount_minor=offer.total_amount_minor,
                    offer_valid_until=offer.valid_until,
                    operator_legal_name=offer.operator_legal_name,
                    aircraft_registration=offer.aircraft_registration,
                    aircraft_manufacturer=offer.aircraft_manufacturer,
                    aircraft_model=offer.aircraft_model,
                    aircraft_category=offer.aircraft_category,
                )
            )
            self.session.flush()
            if on_commit is not None:
                on_commit(self.session)
            return booking

    # -- Operator actions ---------------------------------------------------

    def confirm(self, booking_id: UUID, data: BookingConfirm) -> Booking:
        with self.session.begin():
            booking = self.bookings.get_for_update(booking_id)
            if booking is None:
                raise _not_found("Booking")
            if booking.operator_id != data.operator_id:
                raise OperatorMismatchError("Operator does not match the booking")
            validate_booking_transition(booking.status, BookingStatus.CONFIRMED)

            offer = self.offers.get(booking.operator_offer_id)
            if offer is None or offer.status is not OfferStatus.SELECTED:
                raise BookingEligibilityError(
                    "The selected offer is no longer the authoritative commercial basis"
                )

            # Phase 6 recheck: compliance can lapse after an offer is created, so
            # re-evaluate current operator/aircraft eligibility before confirming.
            # Locks admission/authorization rows so a concurrent suspension cannot
            # yield a booking confirmed under suspended compliance. The booking is
            # not mutated on failure; history is preserved.
            decision = ComplianceEvaluator(self.session).evaluate_operator_aircraft(
                booking.operator_id, booking.aircraft_id, lock=True
            )
            if not decision.eligible:
                raise ComplianceGateError(
                    "Operator or aircraft is not currently eligible to confirm this booking",
                    decision.reasons,
                )

            booking.status = BookingStatus.CONFIRMED
            booking.confirmed_at = _utc_now()
            booking.operator_confirmation_reference = data.confirmation_reference
            booking.confirmation_note = data.note
            self.session.flush()
            return booking

    def reject(self, booking_id: UUID, data: BookingReject) -> Booking:
        with self.session.begin():
            booking = self.bookings.get_for_update(booking_id)
            if booking is None:
                raise _not_found("Booking")
            if booking.operator_id != data.operator_id:
                raise OperatorMismatchError("Operator does not match the booking")
            validate_booking_transition(booking.status, BookingStatus.REJECTED)

            booking.status = BookingStatus.REJECTED
            booking.rejected_at = _utc_now()
            booking.rejection_reason = data.reason
            booking.rejection_note = data.note
            self.session.flush()
            return booking

    # -- Cancellation (customer / operator / platform) ----------------------

    def cancel(
        self, booking_id: UUID, data: BookingCancel, *, on_commit: OnCommit = None
    ) -> Booking:
        with self.session.begin():
            booking = self.bookings.get_for_update(booking_id)
            if booking is None:
                raise _not_found("Booking")
            validate_booking_transition(booking.status, BookingStatus.CANCELLED)

            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = _utc_now()
            booking.cancellation_actor = data.actor
            booking.cancellation_reason = data.reason
            booking.cancellation_note = data.note
            self.session.flush()
            if on_commit is not None:
                on_commit(self.session)
            return booking

    # -- Reads --------------------------------------------------------------

    def get(self, booking_id: UUID) -> Booking:
        booking = self.bookings.get(booking_id)
        if booking is None:
            raise _not_found("Booking")
        return booking

    def get_for_trip(self, trip_request_id: UUID) -> Booking:
        if self.trips.get(trip_request_id) is None:
            raise _not_found("Trip request")
        booking = self.bookings.get_latest_for_trip(trip_request_id)
        if booking is None:
            raise _not_found("Booking")
        return booking
