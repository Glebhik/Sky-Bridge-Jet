from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.repositories import BookingRepository
from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError
from sky_bridge_jet.modules.flight_operations.domain import FlightOperationEligibilityError
from sky_bridge_jet.modules.flight_operations.models import FlightOperation
from sky_bridge_jet.modules.flight_operations.repositories import FlightOperationRepository
from sky_bridge_jet.modules.flight_operations.schemas import (
    OperatorFlightOperationLeg,
    OperatorFlightOperationView,
)


class FlightOperationService:
    """Transaction-neutral creation and bounded safe reads for D0."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.operations = FlightOperationRepository(session)
        self.bookings = BookingRepository(session)

    def ensure_for_confirmed_booking(self, booking_id: UUID) -> FlightOperation:
        booking = self.bookings.get_for_update(booking_id)
        if booking is None:
            raise ResourceNotFoundError("Booking not found")
        if booking.status is not BookingStatus.CONFIRMED:
            raise FlightOperationEligibilityError(
                "Operational handoff requires a confirmed Booking"
            )
        existing = self.operations.get_by_booking(booking.id)
        if existing is not None:
            return existing
        operation = self.operations.add(FlightOperation(booking_id=booking.id))
        self.session.flush()
        return operation

    def list_for_operator(
        self, operator_id: UUID, *, limit: int, offset: int
    ) -> list[OperatorFlightOperationView]:
        return self._views(
            self.operations.list_for_operator(operator_id, limit=limit, offset=offset)
        )

    def get_for_operator(
        self, operation_id: UUID, operator_id: UUID
    ) -> OperatorFlightOperationView:
        row = self.operations.get_for_operator(operation_id, operator_id)
        if row is None:
            raise ResourceNotFoundError("Flight operation not found")
        return self._views([row])[0]

    def _views(
        self, rows: list[tuple[FlightOperation, Booking]]
    ) -> list[OperatorFlightOperationView]:
        legs_by_trip: dict[UUID, list[OperatorFlightOperationLeg]] = {
            booking.trip_request_id: [] for _, booking in rows
        }
        for (
            trip_id,
            sequence,
            origin,
            destination,
            departure_at,
            passenger_count,
        ) in self.operations.list_leg_rows(list(legs_by_trip)):
            legs_by_trip[trip_id].append(
                OperatorFlightOperationLeg(
                    sequence=sequence,
                    origin_airport_code=origin,
                    destination_airport_code=destination,
                    departure_at=departure_at,
                    passenger_count=passenger_count,
                )
            )
        return [
            OperatorFlightOperationView(
                operation_id=operation.id,
                booking_id=booking.id,
                booking_reference=booking.reference,
                status=operation.status,
                booking_status=booking.status,
                aircraft_registration=booking.aircraft_registration,
                aircraft_manufacturer=booking.aircraft_manufacturer,
                aircraft_model=booking.aircraft_model,
                aircraft_category=booking.aircraft_category,
                legs=legs_by_trip[booking.trip_request_id],
                created_at=operation.created_at,
                updated_at=operation.updated_at,
            )
            for operation, booking in rows
        ]
