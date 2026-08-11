from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sky_bridge_jet.modules.core_aviation.domain import (
    DomainValidationError,
    InvalidTripTransitionError,
    TripRequestStatus,
    validate_airport_code,
    validate_trip_leg,
    validate_trip_transition,
)
from sky_bridge_jet.modules.core_aviation.schemas import (
    AircraftCreate,
    PetRequirementCreate,
)


def test_trip_request_allows_draft_submission() -> None:
    assert (
        validate_trip_transition(TripRequestStatus.DRAFT, TripRequestStatus.SUBMITTED)
        == TripRequestStatus.SUBMITTED
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TripRequestStatus.DRAFT, TripRequestStatus.BOOKED),
        (TripRequestStatus.CANCELLED, TripRequestStatus.SUBMITTED),
        (TripRequestStatus.SUBMITTED, TripRequestStatus.QUOTING),
    ],
)
def test_trip_request_rejects_unavailable_or_invalid_transitions(
    current: TripRequestStatus, target: TripRequestStatus
) -> None:
    with pytest.raises(InvalidTripTransitionError):
        validate_trip_transition(current, target)


def test_airport_codes_are_normalized_and_validated() -> None:
    assert validate_airport_code(" eidw ", field_name="icao_code", length=4) == "EIDW"

    with pytest.raises(DomainValidationError, match="ICAO"):
        validate_airport_code("EI1W", field_name="icao_code", length=4)


def test_trip_leg_rejects_identical_airports_and_naive_departure() -> None:
    airport_id = uuid4()

    with pytest.raises(DomainValidationError, match="different"):
        validate_trip_leg(
            origin_airport_id=airport_id,
            destination_airport_id=airport_id,
            departure_at=datetime.now(UTC),
            passenger_count=1,
        )

    with pytest.raises(DomainValidationError, match="timezone-aware"):
        validate_trip_leg(
            origin_airport_id=uuid4(),
            destination_airport_id=uuid4(),
            departure_at=datetime(2026, 8, 10, 12, 0),
            passenger_count=1,
        )


def test_aircraft_capacity_and_pet_weight_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AircraftCreate(
            operator_id=uuid4(),
            manufacturer="Cessna",
            model="Citation CJ3+",
            category="VERY_LIGHT_JET",
            registration="EI-ABC",
            passenger_capacity=0,
        )

    with pytest.raises(ValidationError):
        PetRequirementCreate(pet_type="DOG", approximate_weight_kg="0")
