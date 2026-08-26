from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from sky_bridge_jet.modules.bookings.domain import ACTIVE_BOOKING_STATUSES, BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.core_aviation.models import Airport, TripLeg


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

    def list_pending_for_operator(
        self, operator_id: UUID, *, limit: int, offset: int
    ) -> list[Booking]:
        statement = (
            select(Booking)
            .where(
                Booking.operator_id == operator_id,
                Booking.status == BookingStatus.PENDING_OPERATOR_CONFIRMATION,
            )
            .order_by(Booking.created_at.asc(), Booking.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement))

    def list_leg_rows(
        self, trip_request_ids: list[UUID]
    ) -> list[tuple[UUID, int, str, str, datetime, int]]:
        if not trip_request_ids:
            return []
        origin = aliased(Airport)
        destination = aliased(Airport)
        statement = (
            select(
                TripLeg.trip_request_id,
                TripLeg.sequence,
                origin.icao_code,
                destination.icao_code,
                TripLeg.departure_at,
                TripLeg.passenger_count,
            )
            .join(origin, TripLeg.origin_airport_id == origin.id)
            .join(destination, TripLeg.destination_airport_id == destination.id)
            .where(TripLeg.trip_request_id.in_(trip_request_ids))
            .order_by(TripLeg.trip_request_id.asc(), TripLeg.sequence.asc())
        )
        return [
            (trip_id, sequence, origin_code, destination_code, departure_at, passenger_count)
            for trip_id, sequence, origin_code, destination_code, departure_at, passenger_count in (
                self.session.execute(statement)
            )
        ]
