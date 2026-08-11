from __future__ import annotations

import secrets
from datetime import datetime
from enum import StrEnum
from typing import Final

from sky_bridge_jet.modules.core_aviation.domain import DomainError


class BookingStatus(StrEnum):
    """Booking workflow lifecycle states.

    A selected offer expresses commercial intent; only an operator confirmation
    turns it into a confirmed booking. Rejected and cancelled are terminal and
    remain auditable.
    """

    PENDING_OPERATOR_CONFIRMATION = "PENDING_OPERATOR_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RejectionReason(StrEnum):
    """Controlled operator rejection reasons."""

    AIRCRAFT_UNAVAILABLE = "AIRCRAFT_UNAVAILABLE"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    OPERATIONAL_RESTRICTION = "OPERATIONAL_RESTRICTION"
    COMMERCIAL_WITHDRAWAL = "COMMERCIAL_WITHDRAWAL"
    OTHER = "OTHER"


class CancellationActor(StrEnum):
    """Who conceptually initiated a cancellation."""

    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"
    PLATFORM = "PLATFORM"


class CancellationReason(StrEnum):
    """Controlled, non-financial cancellation reasons (no settlement implied)."""

    SCHEDULE_CHANGE = "SCHEDULE_CHANGE"
    NO_LONGER_REQUIRED = "NO_LONGER_REQUIRED"
    OPERATOR_UNAVAILABLE = "OPERATOR_UNAVAILABLE"
    OTHER = "OTHER"


# A trip request may have at most one booking in an active state at a time.
ACTIVE_BOOKING_STATUSES: Final[frozenset[BookingStatus]] = frozenset(
    {BookingStatus.PENDING_OPERATOR_CONFIRMATION, BookingStatus.CONFIRMED}
)

_BOOKING_REFERENCE_PREFIX: Final[str] = "SBJ"
# 8 random bytes (64 bits) rendered as uppercase hex; opaque, non-sequential,
# and not derived from any customer data. Database uniqueness is authoritative.
_BOOKING_REFERENCE_ENTROPY_BYTES: Final[int] = 8


class BookingConflictError(DomainError):
    """Base for booking lifecycle and eligibility conflicts (maps to 409)."""

    code = "booking_conflict"


class InvalidBookingStateError(BookingConflictError):
    """Raised when a booking lifecycle transition is not permitted."""

    code = "invalid_booking_state"


class BookingEligibilityError(BookingConflictError):
    """Raised when a booking cannot be created for the given offer/trip state."""

    code = "booking_not_allowed"


class OperatorMismatchError(BookingConflictError):
    """Raised when an operator action targets a booking owned by another operator."""

    code = "operator_mismatch"


_ALLOWED_BOOKING_TRANSITIONS: Final[dict[BookingStatus, frozenset[BookingStatus]]] = {
    BookingStatus.PENDING_OPERATOR_CONFIRMATION: frozenset(
        {BookingStatus.CONFIRMED, BookingStatus.REJECTED, BookingStatus.CANCELLED}
    ),
    BookingStatus.CONFIRMED: frozenset({BookingStatus.CANCELLED}),
    BookingStatus.REJECTED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
}


def validate_booking_transition(current: BookingStatus, target: BookingStatus) -> BookingStatus:
    """Return the target status when the lifecycle transition is permitted."""
    if target not in _ALLOWED_BOOKING_TRANSITIONS[current]:
        raise InvalidBookingStateError(
            f"Booking cannot transition from {current.value} to {target.value}"
        )
    return target


def is_offer_within_validity(valid_until: datetime | None, *, now: datetime) -> bool:
    """Report whether a selected offer's validity window still covers ``now``."""
    return valid_until is None or now < valid_until


def generate_booking_reference() -> str:
    """Return an opaque, non-PII booking reference; the database enforces uniqueness."""
    token = secrets.token_hex(_BOOKING_REFERENCE_ENTROPY_BYTES).upper()
    return f"{_BOOKING_REFERENCE_PREFIX}-{token}"
