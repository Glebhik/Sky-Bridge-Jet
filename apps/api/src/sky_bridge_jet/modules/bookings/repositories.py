from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.modules.bookings.domain import ACTIVE_BOOKING_STATUSES
from sky_bridge_jet.modules.bookings.models import Booking


class BookingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, booking: Booking) -> Booking:
        self.session.add(booking)
        return booking

    def get(self, booking_id: UUID) -> Booking | None:
        return self.session.get(Booking, booking_id)

    def get_for_update(self, booking_id: UUID) -> Booking | None:
        """Load a booking with a row lock so concurrent commands serialize."""
        return self.session.get(Booking, booking_id, with_for_update=True)

    def get_active_for_trip(self, trip_request_id: UUID) -> Booking | None:
        """Return the active booking workflow for a trip, if any."""
        statement = select(Booking).where(
            Booking.trip_request_id == trip_request_id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        return self.session.scalar(statement)

    def get_latest_for_trip(self, trip_request_id: UUID) -> Booking | None:
        """Return the most recently created booking for a trip, if any."""
        statement = (
            select(Booking)
            .where(Booking.trip_request_id == trip_request_id)
            .order_by(Booking.created_at.desc(), Booking.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)
