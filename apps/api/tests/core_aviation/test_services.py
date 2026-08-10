from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.core_aviation.domain import ConcurrencyConflictError
from sky_bridge_jet.modules.core_aviation.schemas import (
    CustomerCreate,
    PassengerCreate,
    TripLegCreate,
    TripRequestCreate,
)
from sky_bridge_jet.modules.core_aviation.seed import seed_airports
from sky_bridge_jet.modules.core_aviation.services import CustomerService, TripRequestService


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)


def test_create_trip_attaches_customer_passengers_and_requirements(session: Session) -> None:
    airports = seed_airports(session)
    customer = CustomerService(session).create(
        CustomerCreate(
            customer_type="INDIVIDUAL",
            display_name="Aisling Byrne",
            primary_email="AISLING@example.test",
            preferred_currency="EUR",
            timezone="Europe/Dublin",
        )
    )
    passenger = CustomerService(session).create_passenger(
        PassengerCreate(
            customer_id=customer.id,
            first_name="Aisling",
            last_name="Byrne",
            nationality="IE",
        )
    )
    service = TripRequestService(session)
    trip = service.create(
        TripRequestCreate(
            customer_id=customer.id,
            passenger_ids=[passenger.id],
            legs=[
                TripLegCreate(
                    origin_airport_id=airports[0].id,
                    destination_airport_id=airports[1].id,
                    departure_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
                    passenger_count=1,
                )
            ],
            requirements={
                "ground_transport_requested": True,
                "pet": {"pet_type": "DOG", "approximate_weight_kg": "8.5"},
            },
        )
    )

    assert trip.id is not None
    assert trip.passenger_associations[0].passenger_id == passenger.id
    assert trip.pet_requirement is not None
    assert trip.pet_requirement.weight_kg == Decimal("8.5")


def test_trip_service_rejects_stale_command_version(session: Session) -> None:
    airports = seed_airports(session)
    customer = CustomerService(session).create(
        CustomerCreate(
            customer_type="INDIVIDUAL",
            display_name="Aisling Byrne",
            primary_email="aisling@example.test",
            preferred_currency="EUR",
            timezone="Europe/Dublin",
        )
    )
    trip = TripRequestService(session).create(
        TripRequestCreate(
            customer_id=customer.id,
            legs=[
                TripLegCreate(
                    origin_airport_id=airports[0].id,
                    destination_airport_id=airports[1].id,
                    departure_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
                    passenger_count=1,
                )
            ],
        )
    )

    with pytest.raises(ConcurrencyConflictError):
        TripRequestService(session).submit(trip.id, expected_version=trip.version + 1)


def test_airport_seed_is_idempotent_and_uses_valid_timezone_reference_data(
    session: Session,
) -> None:
    first_seed = seed_airports(session)
    second_seed = seed_airports(session)

    assert len(first_seed) == 9
    assert len(second_seed) == 9
    assert [airport.id for airport in first_seed] == [airport.id for airport in second_seed]
    assert len({airport.icao_code for airport in second_seed}) == len(second_seed)
    assert all("/" in airport.timezone for airport in second_seed)
