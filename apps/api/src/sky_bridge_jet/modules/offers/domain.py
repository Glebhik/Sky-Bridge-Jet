from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final

from sky_bridge_jet.modules.core_aviation.domain import (
    DomainError,
    DomainValidationError,
    validate_aware_datetime,
    validate_currency_code,
)


class OfferStatus(StrEnum):
    """Persisted operator-offer lifecycle states.

    ``EXPIRED`` is deliberately absent: expiration is an effective condition
    derived from ``valid_until`` and the current time (see
    :class:`EffectiveOfferStatus`), so no background scheduler is required to
    keep persisted state correct.
    """

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    SELECTED = "SELECTED"


class EffectiveOfferStatus(StrEnum):
    """Status presented to API consumers, including the derived ``EXPIRED``."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    SELECTED = "SELECTED"


# Phase 3 supports these ISO 4217 currencies at the domain and API level. All
# three are minor-unit-scale 2, so a single "minor units" integer representation
# is unambiguous. No FX conversion is performed; one offer uses one currency.
SUPPORTED_CURRENCIES: Final[frozenset[str]] = frozenset({"EUR", "GBP", "USD"})

# The Sky Bridge Jet platform fee is derived from the operator amount by a simple
# deterministic policy so it can be represented and tested now while remaining
# replaceable. This is intentionally not a pricing engine (see ADR-014).
DEFAULT_PLATFORM_FEE_BPS: Final[int] = 900  # 9.00% expressed in basis points

_MAX_FEE_BPS: Final[int] = 10_000


class OfferConflictError(DomainError):
    """Base for offer lifecycle, eligibility, and selection conflicts (maps to 409)."""

    code = "offer_conflict"


class InvalidOfferStateError(OfferConflictError):
    """Raised when an offer lifecycle transition is not permitted."""

    code = "invalid_offer_state"


class OfferNotSelectableError(OfferConflictError):
    """Raised when an offer cannot be selected in its current state."""

    code = "offer_not_selectable"


class TripNotAcceptingOffersError(OfferConflictError):
    """Raised when a trip request is not in a state that can receive offers."""

    code = "trip_not_accepting_offers"


_ALLOWED_OFFER_TRANSITIONS: Final[dict[OfferStatus, frozenset[OfferStatus]]] = {
    OfferStatus.DRAFT: frozenset({OfferStatus.SUBMITTED, OfferStatus.WITHDRAWN}),
    OfferStatus.SUBMITTED: frozenset({OfferStatus.WITHDRAWN, OfferStatus.SELECTED}),
    OfferStatus.WITHDRAWN: frozenset(),
    OfferStatus.SELECTED: frozenset(),
}


def validate_supported_currency(value: str) -> str:
    """Return the normalized ISO 4217 code when it is a supported Phase 3 currency."""
    normalized = validate_currency_code(value)
    if normalized not in SUPPORTED_CURRENCIES:
        supported = ", ".join(sorted(SUPPORTED_CURRENCIES))
        raise DomainValidationError(f"Currency must be one of {supported}")
    return normalized


def validate_non_negative_minor(value: int, *, field_name: str) -> int:
    """Reject negative monetary amounts; money is stored as integer minor units."""
    if value < 0:
        raise DomainValidationError(f"{field_name} must not be negative")
    return value


def compute_platform_fee_minor(
    operator_amount_minor: int, *, fee_bps: int = DEFAULT_PLATFORM_FEE_BPS
) -> int:
    """Derive the platform fee (minor units) from the operator amount.

    Deterministic integer floor arithmetic keeps totals exact. The policy is a
    single pure function so future commission models can replace it without
    touching the offer aggregate.
    """
    validate_non_negative_minor(operator_amount_minor, field_name="Operator amount")
    if not 0 <= fee_bps <= _MAX_FEE_BPS:
        raise DomainValidationError("Platform fee basis points must be between 0 and 10000")
    return operator_amount_minor * fee_bps // _MAX_FEE_BPS


def compute_total_minor(
    *, operator_amount_minor: int, platform_fee_minor: int, tax_amount_minor: int
) -> int:
    """Return the customer total as the exact sum of the price components."""
    return operator_amount_minor + platform_fee_minor + tax_amount_minor


def validate_price_consistency(
    *,
    operator_amount_minor: int,
    platform_fee_minor: int,
    tax_amount_minor: int,
    total_amount_minor: int,
) -> None:
    """Ensure the stored total equals operator amount plus platform fee plus taxes."""
    for value, field_name in (
        (operator_amount_minor, "Operator amount"),
        (platform_fee_minor, "Platform fee"),
        (tax_amount_minor, "Tax amount"),
        (total_amount_minor, "Total amount"),
    ):
        validate_non_negative_minor(value, field_name=field_name)
    expected = compute_total_minor(
        operator_amount_minor=operator_amount_minor,
        platform_fee_minor=platform_fee_minor,
        tax_amount_minor=tax_amount_minor,
    )
    if total_amount_minor != expected:
        raise DomainValidationError(
            "Offer total must equal operator amount plus platform fee plus taxes"
        )


def validate_future_validity(valid_until: datetime, *, now: datetime) -> datetime:
    """Require a timezone-aware ``valid_until`` strictly in the future at submission."""
    validate_aware_datetime(valid_until)
    if valid_until <= now:
        raise DomainValidationError("Offer validity must be in the future")
    return valid_until


def validate_offer_transition(current: OfferStatus, target: OfferStatus) -> OfferStatus:
    """Return the target status when the lifecycle transition is permitted."""
    if target not in _ALLOWED_OFFER_TRANSITIONS[current]:
        raise InvalidOfferStateError(
            f"Offer cannot transition from {current.value} to {target.value}"
        )
    return target


def is_effectively_expired(
    status: OfferStatus, valid_until: datetime | None, *, now: datetime
) -> bool:
    """Report whether a submitted offer has passed its validity window."""
    return status is OfferStatus.SUBMITTED and valid_until is not None and now >= valid_until


def effective_offer_status(
    status: OfferStatus, valid_until: datetime | None, *, now: datetime
) -> EffectiveOfferStatus:
    """Map a stored status to the effective status, deriving ``EXPIRED`` from time."""
    if is_effectively_expired(status, valid_until, now=now):
        return EffectiveOfferStatus.EXPIRED
    return EffectiveOfferStatus(status.value)
