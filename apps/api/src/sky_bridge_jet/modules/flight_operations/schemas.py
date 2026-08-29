from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.flight_operations.domain import FlightOperationStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OperatorFlightOperationLeg(ApiModel):
    sequence: int
    origin_airport_code: str
    destination_airport_code: str
    departure_at: datetime
    passenger_count: int


class OperatorFlightOperationView(ApiModel):
    operation_id: UUID
    booking_id: UUID
    booking_reference: str
    status: FlightOperationStatus
    booking_status: BookingStatus
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    legs: list[OperatorFlightOperationLeg]
    created_at: datetime
    updated_at: datetime
