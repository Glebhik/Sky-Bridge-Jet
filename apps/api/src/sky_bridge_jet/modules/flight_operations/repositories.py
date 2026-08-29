from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.core_aviation.models import Airport, TripLeg
from sky_bridge_jet.modules.flight_operations.models import FlightOperation


class FlightOperationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, operation: FlightOperation) -> FlightOperation:
        self.session.add(operation)
        return operation

    def get(self, operation_id: UUID) -> FlightOperation | None:
        return self.session.get(FlightOperation, operation_id)

    def get_by_booking(self, booking_id: UUID) -> FlightOperation | None:
        return self.session.scalar(
            select(FlightOperation).where(FlightOperation.booking_id == booking_id)
        )

    def list_for_operator(
        self, operator_id: UUID, *, limit: int, offset: int
    ) -> list[tuple[FlightOperation, Booking]]:
        statement = (
            select(FlightOperation, Booking)
            .join(Booking, Booking.id == FlightOperation.booking_id)
            .where(Booking.operator_id == operator_id)
            .order_by(FlightOperation.created_at.desc(), FlightOperation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(statement).tuples())

    def get_for_operator(
        self, operation_id: UUID, operator_id: UUID
    ) -> tuple[FlightOperation, Booking] | None:
        statement = (
            select(FlightOperation, Booking)
            .join(Booking, Booking.id == FlightOperation.booking_id)
            .where(FlightOperation.id == operation_id, Booking.operator_id == operator_id)
        )
        return self.session.execute(statement).tuples().one_or_none()

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
        return list(self.session.execute(statement).tuples())
