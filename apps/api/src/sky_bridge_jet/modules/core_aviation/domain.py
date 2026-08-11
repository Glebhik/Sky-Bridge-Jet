from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CustomerType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"


class CustomerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OperatorStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AircraftCategory(StrEnum):
    VERY_LIGHT_JET = "VERY_LIGHT_JET"
    LIGHT_JET = "LIGHT_JET"
    MIDSIZE_JET = "MIDSIZE_JET"
    SUPER_MIDSIZE_JET = "SUPER_MIDSIZE_JET"
    HEAVY_JET = "HEAVY_JET"
    ULTRA_LONG_RANGE = "ULTRA_LONG_RANGE"
    VIP_AIRLINER = "VIP_AIRLINER"
    TURBOPROP = "TURBOPROP"


class AircraftStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TripRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUOTING = "QUOTING"
    QUOTES_AVAILABLE = "QUOTES_AVAILABLE"
    QUOTE_SELECTED = "QUOTE_SELECTED"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PetType(StrEnum):
    DOG = "DOG"
    CAT = "CAT"
    OTHER = "OTHER"


class DomainError(Exception):
    """Base class for expected domain failures safe to present to API consumers."""

    code: str = "domain_error"


class DomainValidationError(DomainError, ValueError):
    code = "domain_validation_error"


class ResourceNotFoundError(DomainError):
    code = "resource_not_found"


class InvalidTripTransitionError(DomainError):
    code = "invalid_state_transition"


class ConcurrencyConflictError(DomainError):
    code = "concurrency_conflict"


_AIRPORT_CODE_PATTERN: Final = re.compile(r"^[A-Z]{3,4}$")
_COUNTRY_CODE_PATTERN: Final = re.compile(r"^[A-Z]{2}$")
_CURRENCY_PATTERN: Final = re.compile(r"^[A-Z]{3}$")
_LANGUAGE_PATTERN: Final = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_EMAIL_PATTERN: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REGISTRATION_PATTERN: Final = re.compile(r"^[A-Z0-9][A-Z0-9 -]{1,18}[A-Z0-9]$")

_ALLOWED_TRIP_TRANSITIONS: Final[dict[TripRequestStatus, frozenset[TripRequestStatus]]] = {
    TripRequestStatus.DRAFT: frozenset({TripRequestStatus.SUBMITTED, TripRequestStatus.CANCELLED}),
    TripRequestStatus.SUBMITTED: frozenset({TripRequestStatus.CANCELLED}),
    TripRequestStatus.QUOTING: frozenset(),
    TripRequestStatus.QUOTES_AVAILABLE: frozenset(),
    TripRequestStatus.QUOTE_SELECTED: frozenset(),
    TripRequestStatus.BOOKED: frozenset(),
    TripRequestStatus.CANCELLED: frozenset(),
    TripRequestStatus.EXPIRED: frozenset(),
}


def validate_airport_code(value: str, *, field_name: str, length: int) -> str:
    normalized = value.strip().upper()
    if len(normalized) != length or not _AIRPORT_CODE_PATTERN.fullmatch(normalized):
        label = "ICAO" if field_name == "icao_code" else "IATA"
        raise DomainValidationError(f"{label} code must contain {length} letters")
    return normalized


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise DomainValidationError("Primary email must be a valid email address")
    return normalized


def validate_country_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _COUNTRY_CODE_PATTERN.fullmatch(normalized):
        raise DomainValidationError("Country code must be a two-letter ISO 3166-1 alpha-2 code")
    return normalized


def validate_currency_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise DomainValidationError("Preferred currency must be a three-letter ISO 4217 code")
    return normalized


def validate_language_tag(value: str) -> str:
    normalized = value.strip()
    if not _LANGUAGE_PATTERN.fullmatch(normalized):
        raise DomainValidationError("Preferred language must use a supported BCP 47 language tag")
    return normalized


def validate_timezone(value: str) -> str:
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise DomainValidationError("Timezone must be a valid IANA timezone identifier") from error
    return normalized


def normalize_registration(value: str) -> str:
    normalized = " ".join(value.strip().upper().split())
    if not _REGISTRATION_PATTERN.fullmatch(normalized):
        raise DomainValidationError("Aircraft registration has an invalid format")
    return normalized


def normalize_required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be blank")
    return normalized


def validate_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError("Departure time must be timezone-aware")
    return value


def validate_trip_leg(
    *,
    origin_airport_id: UUID,
    destination_airport_id: UUID,
    departure_at: datetime,
    passenger_count: int,
) -> None:
    if origin_airport_id == destination_airport_id:
        raise DomainValidationError("Trip leg origin and destination must be different")
    validate_aware_datetime(departure_at)
    if passenger_count <= 0:
        raise DomainValidationError("Trip leg passenger count must be greater than zero")


def validate_trip_transition(
    current: TripRequestStatus, target: TripRequestStatus
) -> TripRequestStatus:
    if target not in _ALLOWED_TRIP_TRANSITIONS[current]:
        raise InvalidTripTransitionError(
            f"Trip request cannot transition from {current.value} to {target.value}"
        )
    return target
