from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from sky_bridge_jet.modules.core_aviation.domain import (
    ConcurrencyConflictError,
    DomainValidationError,
    ResourceNotFoundError,
    TripRequestStatus,
    validate_trip_transition,
)
from sky_bridge_jet.modules.core_aviation.models import (
    Aircraft,
    Airport,
    Customer,
    Operator,
    Passenger,
    TripLeg,
    TripPassenger,
    TripPetRequirement,
    TripRequest,
)
from sky_bridge_jet.modules.core_aviation.repositories import (
    AircraftRepository,
    AirportRepository,
    CustomerRepository,
    OperatorRepository,
    PassengerRepository,
    TripRequestRepository,
)
from sky_bridge_jet.modules.core_aviation.schemas import (
    AircraftCreate,
    CustomerCreate,
    OperatorCreate,
    PassengerCreate,
    TripRequestCreate,
)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


class CustomerService:
    """Own customer and passenger use cases; repositories never commit independently."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.customers = CustomerRepository(session)
        self.passengers = PassengerRepository(session)

    def create(self, data: CustomerCreate) -> Customer:
        with self.session.begin():
            customer = self.customers.add(
                Customer(
                    customer_type=data.customer_type,
                    display_name=data.display_name.strip(),
                    primary_email=data.primary_email,
                    primary_phone=data.primary_phone,
                    preferred_language=data.preferred_language,
                    preferred_currency=data.preferred_currency,
                    timezone=data.timezone,
                )
            )
            self.session.flush()
            return customer

    def get(self, customer_id: UUID) -> Customer:
        customer = self.customers.get(customer_id)
        if customer is None:
            raise _not_found("Customer")
        return customer

    def create_passenger(self, data: PassengerCreate) -> Passenger:
        with self.session.begin():
            if self.customers.get(data.customer_id) is None:
                raise _not_found("Customer")
            passenger = self.passengers.add(
                Passenger(
                    customer_id=data.customer_id,
                    first_name=data.first_name.strip(),
                    last_name=data.last_name.strip(),
                    date_of_birth=data.date_of_birth,
                    nationality=data.nationality,
                    contact_email=data.contact_email,
                    contact_phone=data.contact_phone,
                )
            )
            self.session.flush()
            return passenger

    def get_passenger(self, passenger_id: UUID) -> Passenger:
        passenger = self.passengers.get(passenger_id)
        if passenger is None:
            raise _not_found("Passenger")
        return passenger


class AirportService:
    def __init__(self, session: Session) -> None:
        self.airports = AirportRepository(session)

    def list_active(self) -> list[Airport]:
        return list(self.airports.list_active())

    def get(self, airport_id: UUID) -> Airport:
        airport = self.airports.get(airport_id)
        if airport is None:
            raise _not_found("Airport")
        return airport


class OperatorService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.operators = OperatorRepository(session)
        self.aircraft = AircraftRepository(session)

    def create(self, data: OperatorCreate) -> Operator:
        with self.session.begin():
            operator = self.operators.add(
                Operator(
                    legal_name=data.legal_name.strip(),
                    trading_name=data.trading_name.strip() if data.trading_name else None,
                    country_code=data.country_code,
                    contact_email=data.contact_email,
                    contact_phone=data.contact_phone,
                )
            )
            self.session.flush()
            return operator

    def get(self, operator_id: UUID) -> Operator:
        operator = self.operators.get(operator_id)
        if operator is None:
            raise _not_found("Operator")
        return operator

    def create_aircraft(self, data: AircraftCreate) -> Aircraft:
        with self.session.begin():
            if self.operators.get(data.operator_id) is None:
                raise _not_found("Operator")
            aircraft = self.aircraft.add(
                Aircraft(
                    operator_id=data.operator_id,
                    manufacturer=data.manufacturer.strip(),
                    model=data.model.strip(),
                    category=data.category,
                    registration=data.registration,
                    passenger_capacity=data.passenger_capacity,
                )
            )
            self.session.flush()
            return aircraft

    def get_aircraft(self, aircraft_id: UUID) -> Aircraft:
        aircraft = self.aircraft.get(aircraft_id)
        if aircraft is None:
            raise _not_found("Aircraft")
        return aircraft


class TripRequestService:
    """Own aggregate writes and their transaction boundary, including optimistic version checks."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.customers = CustomerRepository(session)
        self.passengers = PassengerRepository(session)
        self.airports = AirportRepository(session)
        self.trips = TripRequestRepository(session)

    def create(self, data: TripRequestCreate) -> TripRequest:
        with self.session.begin():
            if self.customers.get(data.customer_id) is None:
                raise _not_found("Customer")

            trip = self.trips.add(
                TripRequest(
                    customer_id=data.customer_id,
                    baggage_notes=data.requirements.baggage_notes,
                    catering_notes=data.requirements.catering_notes,
                    ground_transport_requested=data.requirements.ground_transport_requested,
                    special_assistance_notes=data.requirements.special_assistance_notes,
                    customer_notes=data.requirements.customer_notes,
                )
            )
            for sequence, leg_data in enumerate(data.legs, start=1):
                origin = self.airports.get(leg_data.origin_airport_id)
                destination = self.airports.get(leg_data.destination_airport_id)
                if origin is None:
                    raise _not_found("Origin airport")
                if destination is None:
                    raise _not_found("Destination airport")
                trip.legs.append(
                    TripLeg(
                        sequence=sequence,
                        origin_airport_id=origin.id,
                        destination_airport_id=destination.id,
                        departure_at=leg_data.departure_at,
                        origin_timezone=origin.timezone,
                        destination_timezone=destination.timezone,
                        passenger_count=leg_data.passenger_count,
                    )
                )

            for passenger_id in data.passenger_ids:
                passenger = self.passengers.get(passenger_id)
                if passenger is None:
                    raise _not_found("Passenger")
                if passenger.customer_id != data.customer_id:
                    raise DomainValidationError(
                        "Passengers must belong to the trip request customer"
                    )
                trip.passenger_associations.append(TripPassenger(passenger=passenger))

            if data.requirements.pet is not None:
                trip.pet_requirement = TripPetRequirement(
                    pet_type=data.requirements.pet.pet_type,
                    weight_kg=data.requirements.pet.approximate_weight_kg,
                    notes=data.requirements.pet.notes,
                )
            self.session.flush()
            return trip

    def get(self, trip_request_id: UUID) -> TripRequest:
        trip = self.trips.get(trip_request_id)
        if trip is None:
            raise _not_found("Trip request")
        return trip

    def submit(self, trip_request_id: UUID, *, expected_version: int) -> TripRequest:
        return self._transition(
            trip_request_id,
            expected_version=expected_version,
            target=TripRequestStatus.SUBMITTED,
        )

    def cancel(self, trip_request_id: UUID, *, expected_version: int) -> TripRequest:
        return self._transition(
            trip_request_id,
            expected_version=expected_version,
            target=TripRequestStatus.CANCELLED,
        )

    def _transition(
        self,
        trip_request_id: UUID,
        *,
        expected_version: int,
        target: TripRequestStatus,
    ) -> TripRequest:
        try:
            with self.session.begin():
                trip = self.get(trip_request_id)
                if trip.version != expected_version:
                    raise ConcurrencyConflictError(
                        "Trip request has changed; refresh it before trying again"
                    )
                trip.status = validate_trip_transition(trip.status, target)
                self.session.flush()
                return trip
        except StaleDataError as error:
            raise ConcurrencyConflictError(
                "Trip request has changed; refresh it before trying again"
            ) from error


def translate_integrity_error(error: IntegrityError) -> ValueError:
    """Convert uniqueness and FK conflicts into a safe API-facing conflict without SQL details."""
    raise ValueError("A resource with the supplied unique value already exists") from error
