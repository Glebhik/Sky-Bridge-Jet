import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.db.session import SessionLocal, engine
from sky_bridge_jet.modules.core_aviation.models import TripPassenger
from sky_bridge_jet.modules.core_aviation.schemas import (
    CustomerCreate,
    PassengerCreate,
    TripLegCreate,
    TripRequestCreate,
)
from sky_bridge_jet.modules.core_aviation.seed import seed_airports
from sky_bridge_jet.modules.core_aviation.services import CustomerService, TripRequestService

_INTEGRATION = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _new_customer(session, display_name: str):
    return CustomerService(session).create(
        CustomerCreate(
            customer_type="INDIVIDUAL",
            display_name=display_name,
            primary_email=f"owner-{uuid4()}@example.test",
            preferred_currency="EUR",
            timezone="Europe/Dublin",
        )
    )


def _new_passenger(session, customer_id):
    return CustomerService(session).create_passenger(
        PassengerCreate(customer_id=customer_id, first_name="Guest", last_name="Passenger")
    )


def _new_trip(session, customer_id, airports):
    return TripRequestService(session).create(
        TripRequestCreate(
            customer_id=customer_id,
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


@pytest.mark.integration
@_INTEGRATION
def test_postgresql_migration_and_trip_persistence() -> None:
    inspector = inspect(engine)
    assert {"customers", "airports", "trip_requests", "trip_legs"} <= set(
        inspector.get_table_names()
    )

    with SessionLocal() as session:
        airports = seed_airports(session)
        customer = CustomerService(session).create(
            CustomerCreate(
                customer_type="INDIVIDUAL",
                display_name="Integration Customer",
                primary_email=f"integration-{uuid4()}@example.test",
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

    with SessionLocal() as verification_session:
        persisted_trip = TripRequestService(verification_session).get(trip.id)

    assert persisted_trip.legs[0].origin_timezone == "Europe/Dublin"


@pytest.mark.integration
@_INTEGRATION
def test_same_customer_passenger_association_persists() -> None:
    with SessionLocal() as session:
        airports = seed_airports(session)
        customer = _new_customer(session, "Owner Customer")
        passenger = _new_passenger(session, customer.id)
        trip = _new_trip(session, customer.id, airports)
        customer_id, passenger_id, trip_id = customer.id, passenger.id, trip.id

    with SessionLocal() as session:
        session.add(
            TripPassenger(
                trip_request_id=trip_id, passenger_id=passenger_id, customer_id=customer_id
            )
        )
        session.commit()

    with SessionLocal() as verification_session:
        persisted_trip = TripRequestService(verification_session).get(trip_id)
        assert [a.passenger_id for a in persisted_trip.passenger_associations] == [passenger_id]


@pytest.mark.integration
@_INTEGRATION
def test_database_rejects_cross_customer_passenger_association_bypassing_service() -> None:
    """The database must reject a mismatched association even without the service layer."""
    with SessionLocal() as session:
        airports = seed_airports(session)
        customer_a = _new_customer(session, "Customer A")
        customer_b = _new_customer(session, "Customer B")
        passenger_b = _new_passenger(session, customer_b.id)
        trip_a = _new_trip(session, customer_a.id, airports)
        customer_a_id, customer_b_id = customer_a.id, customer_b.id
        passenger_b_id, trip_a_id = passenger_b.id, trip_a.id

    # No value of customer_id can satisfy both composite foreign keys when the
    # passenger and trip request belong to different customers.
    for forced_customer_id in (customer_a_id, customer_b_id):
        with SessionLocal() as session:
            session.add(
                TripPassenger(
                    trip_request_id=trip_a_id,
                    passenger_id=passenger_b_id,
                    customer_id=forced_customer_id,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
