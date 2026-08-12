import re

import pytest

from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.payments.domain import (
    InvalidPaymentStateError,
    PaymentStatus,
    SettlementEligibility,
    compute_settlement_eligibility,
    generate_payment_reference,
    is_authorizable,
    is_booking_payable,
    is_capturable,
    is_refundable,
    is_voidable,
    refund_status_after,
    validate_payment_transition,
)
from sky_bridge_jet.modules.payments.provider import (
    DECLINE_AUTHORIZATION,
    DECLINE_CAPTURE,
    DECLINE_REFUND,
    FakePaymentProvider,
    ProviderOutcome,
)


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        (PaymentStatus.CREATED, PaymentStatus.AUTHORIZED, True),
        (PaymentStatus.CREATED, PaymentStatus.AUTHORIZATION_FAILED, True),
        (PaymentStatus.AUTHORIZATION_FAILED, PaymentStatus.AUTHORIZED, True),
        (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED, True),
        (PaymentStatus.AUTHORIZED, PaymentStatus.CANCELLED, True),
        (PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED, True),
        (PaymentStatus.CAPTURED, PaymentStatus.REFUNDED, True),
        # Illegal transitions.
        (PaymentStatus.CREATED, PaymentStatus.CAPTURED, False),
        (PaymentStatus.AUTHORIZED, PaymentStatus.REFUNDED, False),
        (PaymentStatus.CAPTURED, PaymentStatus.CANCELLED, False),
        (PaymentStatus.CANCELLED, PaymentStatus.AUTHORIZED, False),
        (PaymentStatus.REFUNDED, PaymentStatus.CAPTURED, False),
    ],
)
def test_payment_transitions(current: PaymentStatus, target: PaymentStatus, allowed: bool) -> None:
    if allowed:
        assert validate_payment_transition(current, target) == target
    else:
        with pytest.raises(InvalidPaymentStateError):
            validate_payment_transition(current, target)


def test_predicates() -> None:
    assert is_authorizable(PaymentStatus.CREATED)
    assert not is_authorizable(PaymentStatus.AUTHORIZED)
    assert is_capturable(PaymentStatus.AUTHORIZED)
    assert not is_capturable(PaymentStatus.CREATED)
    assert is_voidable(PaymentStatus.AUTHORIZED)
    assert not is_voidable(PaymentStatus.CAPTURED)
    assert is_refundable(PaymentStatus.CAPTURED)
    assert not is_refundable(PaymentStatus.AUTHORIZED)


def test_booking_payable() -> None:
    assert is_booking_payable(BookingStatus.PENDING_OPERATOR_CONFIRMATION)
    assert is_booking_payable(BookingStatus.CONFIRMED)
    assert not is_booking_payable(BookingStatus.REJECTED)
    assert not is_booking_payable(BookingStatus.CANCELLED)


def test_refund_status_after() -> None:
    assert refund_status_after(captured_minor=1000, refunded_minor=400) == (
        PaymentStatus.PARTIALLY_REFUNDED
    )
    assert refund_status_after(captured_minor=1000, refunded_minor=1000) == PaymentStatus.REFUNDED


def test_settlement_eligibility() -> None:
    eligible = compute_settlement_eligibility(
        payment_status=PaymentStatus.CAPTURED,
        booking_status=BookingStatus.CONFIRMED,
        captured_minor=1000,
        refunded_minor=0,
    )
    assert eligible == SettlementEligibility.ELIGIBLE
    # A refund removes eligibility (refund apportionment is deferred policy).
    assert (
        compute_settlement_eligibility(
            payment_status=PaymentStatus.PARTIALLY_REFUNDED,
            booking_status=BookingStatus.CONFIRMED,
            captured_minor=1000,
            refunded_minor=100,
        )
        == SettlementEligibility.NOT_ELIGIBLE
    )
    # Not captured, or booking not confirmed.
    assert (
        compute_settlement_eligibility(
            payment_status=PaymentStatus.AUTHORIZED,
            booking_status=BookingStatus.CONFIRMED,
            captured_minor=0,
            refunded_minor=0,
        )
        == SettlementEligibility.NOT_ELIGIBLE
    )


def test_reference_opaque_and_unique() -> None:
    pattern = re.compile(r"\APAY-[0-9A-F]{16}\Z")
    refs = {generate_payment_reference() for _ in range(1000)}
    assert len(refs) == 1000
    assert all(pattern.match(r) for r in refs)


def test_fake_provider_deterministic_outcomes() -> None:
    provider = FakePaymentProvider()

    ok = provider.authorize(
        amount_minor=1000, currency="EUR", payment_method_reference=None, idempotency_key="k-ok"
    )
    assert ok.outcome is ProviderOutcome.SUCCEEDED and ok.provider_reference is not None
    assert (
        provider.capture(
            provider_reference=ok.provider_reference,
            amount_minor=1000,
            currency="EUR",
            idempotency_key="k-ok-cap",
        ).outcome
        is ProviderOutcome.SUCCEEDED
    )

    declined = provider.authorize(
        amount_minor=1000,
        currency="EUR",
        payment_method_reference=DECLINE_AUTHORIZATION,
        idempotency_key="k-decline",
    )
    assert declined.outcome is ProviderOutcome.FAILED
    assert declined.failure_code == "authorization_declined"

    cap_fail_auth = provider.authorize(
        amount_minor=1000,
        currency="EUR",
        payment_method_reference=DECLINE_CAPTURE,
        idempotency_key="k-capfail",
    )
    assert cap_fail_auth.outcome is ProviderOutcome.SUCCEEDED
    assert cap_fail_auth.provider_reference is not None
    assert (
        provider.capture(
            provider_reference=cap_fail_auth.provider_reference,
            amount_minor=1000,
            currency="EUR",
            idempotency_key="k-capfail-cap",
        ).outcome
        is ProviderOutcome.FAILED
    )

    ref_fail_auth = provider.authorize(
        amount_minor=1000,
        currency="EUR",
        payment_method_reference=DECLINE_REFUND,
        idempotency_key="k-reffail",
    )
    assert ref_fail_auth.provider_reference is not None
    assert (
        provider.refund(
            provider_reference=ref_fail_auth.provider_reference,
            amount_minor=100,
            currency="EUR",
            idempotency_key="k-reffail-ref",
        ).outcome
        is ProviderOutcome.FAILED
    )
