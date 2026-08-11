import re
from datetime import UTC, datetime, timedelta

import pytest

from sky_bridge_jet.modules.bookings.domain import (
    ACTIVE_BOOKING_STATUSES,
    BookingStatus,
    InvalidBookingStateError,
    generate_booking_reference,
    is_offer_within_validity,
    validate_booking_transition,
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        (BookingStatus.PENDING_OPERATOR_CONFIRMATION, BookingStatus.CONFIRMED, True),
        (BookingStatus.PENDING_OPERATOR_CONFIRMATION, BookingStatus.REJECTED, True),
        (BookingStatus.PENDING_OPERATOR_CONFIRMATION, BookingStatus.CANCELLED, True),
        (BookingStatus.CONFIRMED, BookingStatus.CANCELLED, True),
        # Illegal transitions must fail deterministically.
        (BookingStatus.REJECTED, BookingStatus.CONFIRMED, False),
        (BookingStatus.CANCELLED, BookingStatus.CONFIRMED, False),
        (BookingStatus.CONFIRMED, BookingStatus.PENDING_OPERATOR_CONFIRMATION, False),
        (BookingStatus.CONFIRMED, BookingStatus.REJECTED, False),
        (
            BookingStatus.PENDING_OPERATOR_CONFIRMATION,
            BookingStatus.PENDING_OPERATOR_CONFIRMATION,
            False,
        ),
        (BookingStatus.REJECTED, BookingStatus.CANCELLED, False),
    ],
)
def test_booking_transitions(current: BookingStatus, target: BookingStatus, allowed: bool) -> None:
    if allowed:
        assert validate_booking_transition(current, target) == target
    else:
        with pytest.raises(InvalidBookingStateError):
            validate_booking_transition(current, target)


def test_active_statuses() -> None:
    assert ACTIVE_BOOKING_STATUSES == frozenset(
        {BookingStatus.PENDING_OPERATOR_CONFIRMATION, BookingStatus.CONFIRMED}
    )


def test_booking_reference_is_opaque_and_unique() -> None:
    pattern = re.compile(r"\ASBJ-[0-9A-F]{16}\Z")
    references = {generate_booking_reference() for _ in range(1000)}
    assert len(references) == 1000  # no collisions across many generations
    for reference in references:
        assert pattern.match(reference)


def test_offer_within_validity() -> None:
    assert is_offer_within_validity(None, now=_NOW) is True
    assert is_offer_within_validity(_NOW + timedelta(hours=1), now=_NOW) is True
    assert is_offer_within_validity(_NOW - timedelta(seconds=1), now=_NOW) is False
    assert is_offer_within_validity(_NOW, now=_NOW) is False
