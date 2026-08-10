import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from sky_bridge_jet.db.session import SessionLocal, engine
from sky_bridge_jet.modules.core_aviation.schemas import (
    CustomerCreate,
    TripLegCreate,
    TripRequestCreate,
)
from sky_bridge_jet.modules.core_aviation.seed import seed_airports
from sky_bridge_jet.modules.core_aviation.services import CustomerService, TripRequestService


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
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
