from __future__ import annotations

import secrets
from enum import StrEnum
from typing import Final

from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.core_aviation.domain import DomainError


class PaymentStatus(StrEnum):
    """Provider-neutral payment lifecycle states.

    Financial success is never inferred from booking state; it is recorded here
    explicitly as the payment provider (a deterministic fake in Phase 5) reports
    it.
    """

    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    CAPTURED = "CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    CANCELLED = "CANCELLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class PaymentOperationType(StrEnum):
    """A provider-neutral financial command recorded for idempotency and audit."""

    AUTHORIZE = "AUTHORIZE"
    CAPTURE = "CAPTURE"
    VOID = "VOID"
    REFUND = "REFUND"


class PaymentOperationResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SettlementEligibility(StrEnum):
    """Orchestration eligibility for operator settlement.

    This is NOT a payout-timing policy and does not move funds. It reports only
    whether the operator's economic allocation could become settlement-eligible
    under a future, separately approved policy.
    """

    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    ELIGIBLE = "ELIGIBLE"


_PAYMENT_REFERENCE_PREFIX: Final[str] = "PAY"
_PAYMENT_REFERENCE_ENTROPY_BYTES: Final[int] = 8


class PaymentConflictError(DomainError):
    """Base for payment lifecycle and eligibility conflicts (maps to 409)."""

    code = "payment_conflict"


class InvalidPaymentStateError(PaymentConflictError):
    """Raised when a payment lifecycle transition is not permitted."""

    code = "invalid_payment_state"


class PaymentEligibilityError(PaymentConflictError):
    """Raised when a payment command is not allowed for the booking/amount state."""

    code = "payment_not_allowed"


class IdempotencyConflictError(PaymentConflictError):
    """Raised when an idempotency key is reused for a different operation."""

    code = "idempotency_conflict"


_ALLOWED_PAYMENT_TRANSITIONS: Final[dict[PaymentStatus, frozenset[PaymentStatus]]] = {
    PaymentStatus.CREATED: frozenset(
        {
            PaymentStatus.AUTHORIZED,
            PaymentStatus.AUTHORIZATION_FAILED,
            PaymentStatus.CANCELLED,
        }
    ),
    PaymentStatus.AUTHORIZATION_FAILED: frozenset(
        {
            PaymentStatus.AUTHORIZED,
            PaymentStatus.AUTHORIZATION_FAILED,
            PaymentStatus.CANCELLED,
        }
    ),
    PaymentStatus.AUTHORIZED: frozenset(
        {PaymentStatus.CAPTURED, PaymentStatus.CAPTURE_FAILED, PaymentStatus.CANCELLED}
    ),
    PaymentStatus.CAPTURE_FAILED: frozenset(
        {PaymentStatus.CAPTURED, PaymentStatus.CAPTURE_FAILED, PaymentStatus.CANCELLED}
    ),
    PaymentStatus.CAPTURED: frozenset({PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED}),
    PaymentStatus.PARTIALLY_REFUNDED: frozenset(
        {PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED}
    ),
    PaymentStatus.REFUNDED: frozenset(),
    PaymentStatus.CANCELLED: frozenset(),
}

_AUTHORIZABLE: Final[frozenset[PaymentStatus]] = frozenset(
    {PaymentStatus.CREATED, PaymentStatus.AUTHORIZATION_FAILED}
)
_CAPTURABLE: Final[frozenset[PaymentStatus]] = frozenset(
    {PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURE_FAILED}
)
_VOIDABLE: Final[frozenset[PaymentStatus]] = frozenset(
    {
        PaymentStatus.CREATED,
        PaymentStatus.AUTHORIZATION_FAILED,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.CAPTURE_FAILED,
    }
)
_REFUNDABLE: Final[frozenset[PaymentStatus]] = frozenset(
    {PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED}
)

# A payment may be created while the booking is awaiting confirmation or already
# confirmed; a rejected or cancelled booking cannot take on a payment obligation.
_PAYABLE_BOOKING_STATUSES: Final[frozenset[BookingStatus]] = frozenset(
    {BookingStatus.PENDING_OPERATOR_CONFIRMATION, BookingStatus.CONFIRMED}
)


def validate_payment_transition(current: PaymentStatus, target: PaymentStatus) -> PaymentStatus:
    """Return the target status when the transition is permitted, else raise."""
    if target not in _ALLOWED_PAYMENT_TRANSITIONS[current]:
        raise InvalidPaymentStateError(
            f"Payment cannot transition from {current.value} to {target.value}"
        )
    return target


def is_authorizable(status: PaymentStatus) -> bool:
    return status in _AUTHORIZABLE


def is_capturable(status: PaymentStatus) -> bool:
    return status in _CAPTURABLE


def is_voidable(status: PaymentStatus) -> bool:
    return status in _VOIDABLE


def is_refundable(status: PaymentStatus) -> bool:
    return status in _REFUNDABLE


def is_booking_payable(status: BookingStatus) -> bool:
    return status in _PAYABLE_BOOKING_STATUSES


def refund_status_after(*, captured_minor: int, refunded_minor: int) -> PaymentStatus:
    """Return PARTIALLY_REFUNDED or REFUNDED given the new cumulative refund total."""
    if refunded_minor >= captured_minor:
        return PaymentStatus.REFUNDED
    return PaymentStatus.PARTIALLY_REFUNDED


def compute_settlement_eligibility(
    *,
    payment_status: PaymentStatus,
    booking_status: BookingStatus,
    captured_minor: int,
    refunded_minor: int,
) -> SettlementEligibility:
    """Report operator-settlement eligibility (orchestration only, never payout).

    The operator allocation becomes eligible only when the customer payment is
    fully captured, unreduced by refunds, and the booking is confirmed. Refund
    apportionment across operator/platform and payout timing are deferred policy.
    """
    if (
        payment_status is PaymentStatus.CAPTURED
        and booking_status is BookingStatus.CONFIRMED
        and captured_minor > 0
        and refunded_minor == 0
    ):
        return SettlementEligibility.ELIGIBLE
    return SettlementEligibility.NOT_ELIGIBLE


def generate_payment_reference() -> str:
    """Return an opaque, non-PII payment reference; the database enforces uniqueness."""
    token = secrets.token_hex(_PAYMENT_REFERENCE_ENTROPY_BYTES).upper()
    return f"{_PAYMENT_REFERENCE_PREFIX}-{token}"
