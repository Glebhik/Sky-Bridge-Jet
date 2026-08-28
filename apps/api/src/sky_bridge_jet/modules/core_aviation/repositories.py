from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from sky_bridge_jet.modules.core_aviation.models import (
    Aircraft,
    Airport,
    Customer,
    Operator,
    Passenger,
    TripPassenger,
    TripRequest,
)


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, customer: Customer) -> Customer:
        self.session.add(customer)
        return customer

    def get(self, customer_id: UUID) -> Customer | None:
        return self.session.get(Customer, customer_id)


class PassengerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, passenger: Passenger) -> Passenger:
        self.session.add(passenger)
        return passenger

    def get(self, passenger_id: UUID) -> Passenger | None:
        return self.session.get(Passenger, passenger_id)


class AirportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, airport: Airport) -> Airport:
        self.session.add(airport)
        return airport

    def get(self, airport_id: UUID) -> Airport | None:
        return self.session.get(Airport, airport_id)

    def get_by_icao(self, icao_code: str) -> Airport | None:
        return self.session.scalar(select(Airport).where(Airport.icao_code == icao_code))

    def list_active(self) -> Sequence[Airport]:
        statement = select(Airport).where(Airport.is_active.is_(True)).order_by(Airport.icao_code)
        return self.session.scalars(statement).all()


class OperatorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, operator: Operator) -> Operator:
        self.session.add(operator)
        return operator

    def get(self, operator_id: UUID) -> Operator | None:
        return self.session.get(Operator, operator_id)


class AircraftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, aircraft: Aircraft) -> Aircraft:
        self.session.add(aircraft)
        return aircraft

    def get(self, aircraft_id: UUID) -> Aircraft | None:
        return self.session.get(Aircraft, aircraft_id)

    def get_for_operator(self, operator_id: UUID, aircraft_id: UUID) -> Aircraft | None:
        return self.session.scalar(
            select(Aircraft).where(
                Aircraft.id == aircraft_id,
                Aircraft.operator_id == operator_id,
            )
        )

    def list_for_operator(
        self, operator_id: UUID, *, limit: int, offset: int
    ) -> Sequence[Aircraft]:
        statement = (
            select(Aircraft)
            .where(Aircraft.operator_id == operator_id)
            .order_by(Aircraft.registration.asc(), Aircraft.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(statement).all()


class TripRequestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, trip_request: TripRequest) -> TripRequest:
        self.session.add(trip_request)
        return trip_request

    def get(self, trip_request_id: UUID) -> TripRequest | None:
        statement = self._detail_statement().where(TripRequest.id == trip_request_id)
        return self.session.scalar(statement)

    @staticmethod
    def _detail_statement() -> Select[tuple[TripRequest]]:
        return select(TripRequest).options(
            selectinload(TripRequest.legs),
            selectinload(TripRequest.passenger_associations).selectinload(TripPassenger.passenger),
            selectinload(TripRequest.pet_requirement),
        )
