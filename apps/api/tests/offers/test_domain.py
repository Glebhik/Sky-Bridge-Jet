from datetime import UTC, datetime, timedelta

import pytest

from sky_bridge_jet.modules.core_aviation.domain import DomainValidationError
from sky_bridge_jet.modules.offers.domain import (
    DEFAULT_PLATFORM_FEE_BPS,
    EffectiveOfferStatus,
    InvalidOfferStateError,
    OfferStatus,
    compute_platform_fee_minor,
    compute_total_minor,
    effective_offer_status,
    is_effectively_expired,
    validate_future_validity,
    validate_non_negative_minor,
    validate_offer_transition,
    validate_price_consistency,
    validate_supported_currency,
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("code,expected", [("EUR", "EUR"), ("gbp", "GBP"), (" usd ", "USD")])
def test_supported_currency_normalizes(code: str, expected: str) -> None:
    assert validate_supported_currency(code) == expected


@pytest.mark.parametrize("code", ["JPY", "CHF", "EU", "EURO", "123"])
def test_unsupported_or_malformed_currency_rejected(code: str) -> None:
    with pytest.raises(DomainValidationError):
        validate_supported_currency(code)


def test_non_negative_minor_rejects_negative() -> None:
    with pytest.raises(DomainValidationError):
        validate_non_negative_minor(-1, field_name="Amount")
    assert validate_non_negative_minor(0, field_name="Amount") == 0


def test_platform_fee_is_deterministic_floor() -> None:
    assert compute_platform_fee_minor(100_000) == 9_000  # 9% of 100000
    assert compute_platform_fee_minor(12_345) == 1_111  # 12345*900//10000
    assert compute_platform_fee_minor(0) == 0
    assert DEFAULT_PLATFORM_FEE_BPS == 900


def test_platform_fee_rejects_bad_inputs() -> None:
    with pytest.raises(DomainValidationError):
        compute_platform_fee_minor(-1)
    with pytest.raises(DomainValidationError):
        compute_platform_fee_minor(1000, fee_bps=10_001)


def test_total_and_consistency() -> None:
    total = compute_total_minor(
        operator_amount_minor=100_000, platform_fee_minor=9_000, tax_amount_minor=5_000
    )
    assert total == 114_000
    validate_price_consistency(
        operator_amount_minor=100_000,
        platform_fee_minor=9_000,
        tax_amount_minor=5_000,
        total_amount_minor=114_000,
    )


def test_price_consistency_rejects_mismatch_and_negatives() -> None:
    with pytest.raises(DomainValidationError):
        validate_price_consistency(
            operator_amount_minor=100_000,
            platform_fee_minor=9_000,
            tax_amount_minor=5_000,
            total_amount_minor=113_999,
        )
    with pytest.raises(DomainValidationError):
        validate_price_consistency(
            operator_amount_minor=-1,
            platform_fee_minor=0,
            tax_amount_minor=0,
            total_amount_minor=-1,
        )


def test_future_validity() -> None:
    future = _NOW + timedelta(hours=1)
    assert validate_future_validity(future, now=_NOW) == future
    with pytest.raises(DomainValidationError):
        validate_future_validity(_NOW, now=_NOW)
    with pytest.raises(DomainValidationError):
        validate_future_validity(_NOW - timedelta(seconds=1), now=_NOW)
    with pytest.raises(DomainValidationError):
        validate_future_validity(datetime(2026, 9, 1, 13, 0), now=_NOW)  # naive


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        (OfferStatus.DRAFT, OfferStatus.SUBMITTED, True),
        (OfferStatus.DRAFT, OfferStatus.WITHDRAWN, True),
        (OfferStatus.SUBMITTED, OfferStatus.SELECTED, True),
        (OfferStatus.SUBMITTED, OfferStatus.WITHDRAWN, True),
        (OfferStatus.DRAFT, OfferStatus.SELECTED, False),
        (OfferStatus.SUBMITTED, OfferStatus.DRAFT, False),
        (OfferStatus.WITHDRAWN, OfferStatus.SUBMITTED, False),
        (OfferStatus.SELECTED, OfferStatus.WITHDRAWN, False),
    ],
)
def test_offer_transitions(current: OfferStatus, target: OfferStatus, allowed: bool) -> None:
    if allowed:
        assert validate_offer_transition(current, target) == target
    else:
        with pytest.raises(InvalidOfferStateError):
            validate_offer_transition(current, target)


def test_effective_status_derives_expired_only_for_submitted() -> None:
    past = _NOW - timedelta(hours=1)
    future = _NOW + timedelta(hours=1)

    assert is_effectively_expired(OfferStatus.SUBMITTED, past, now=_NOW) is True
    assert effective_offer_status(OfferStatus.SUBMITTED, past, now=_NOW) == (
        EffectiveOfferStatus.EXPIRED
    )
    assert effective_offer_status(OfferStatus.SUBMITTED, future, now=_NOW) == (
        EffectiveOfferStatus.SUBMITTED
    )
    assert effective_offer_status(OfferStatus.SUBMITTED, None, now=_NOW) == (
        EffectiveOfferStatus.SUBMITTED
    )
    # Non-submitted states are never reported as expired.
    assert effective_offer_status(OfferStatus.DRAFT, past, now=_NOW) == EffectiveOfferStatus.DRAFT
    assert is_effectively_expired(OfferStatus.WITHDRAWN, past, now=_NOW) is False
    assert effective_offer_status(OfferStatus.SELECTED, past, now=_NOW) == (
        EffectiveOfferStatus.SELECTED
    )
