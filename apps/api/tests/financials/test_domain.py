"""Pure domain tests for onboarding status derivation and financial eligibility."""

from __future__ import annotations

from sky_bridge_jet.modules.financials.domain import (
    FinancialEligibilityReason,
    OnboardingStatus,
    ProviderAccountSnapshot,
    compute_financial_eligibility,
    derive_onboarding_status,
)


def _snapshot(
    *,
    charges: bool = False,
    payouts: bool = False,
    details: bool = False,
    requirements: bool = False,
    disabled_reason: str | None = None,
) -> ProviderAccountSnapshot:
    return ProviderAccountSnapshot(
        charges_enabled=charges,
        payouts_enabled=payouts,
        details_submitted=details,
        requirements_due=requirements,
        disabled_reason=disabled_reason,
    )


def test_derive_status_enabled_when_charges_and_payouts() -> None:
    assert (
        derive_onboarding_status(_snapshot(charges=True, payouts=True)) is OnboardingStatus.ENABLED
    )


def test_derive_status_restricted_when_only_charges() -> None:
    status = derive_onboarding_status(_snapshot(charges=True, payouts=False))
    assert status is OnboardingStatus.RESTRICTED


def test_derive_status_disabled_when_disabled_reason_and_no_charges() -> None:
    status = derive_onboarding_status(_snapshot(disabled_reason="under_review", charges=False))
    assert status is OnboardingStatus.DISABLED


def test_derive_status_requirements_due_and_under_review_and_pending() -> None:
    assert (
        derive_onboarding_status(_snapshot(requirements=True)) is OnboardingStatus.REQUIREMENTS_DUE
    )
    assert derive_onboarding_status(_snapshot(details=True)) is OnboardingStatus.UNDER_REVIEW
    assert derive_onboarding_status(_snapshot()) is OnboardingStatus.ONBOARDING_PENDING


def test_eligibility_requires_enabled() -> None:
    decision = compute_financial_eligibility(
        status=OnboardingStatus.ENABLED,
        charges_enabled=True,
        payouts_enabled=True,
        requirements_due=False,
    )
    assert decision.eligible is True
    assert decision.reasons == []


def test_eligibility_no_account_is_explainable() -> None:
    decision = compute_financial_eligibility(
        status=None, charges_enabled=False, payouts_enabled=False, requirements_due=True
    )
    assert decision.eligible is False
    assert FinancialEligibilityReason.NO_CONNECTED_ACCOUNT in decision.reasons


def test_eligibility_restricted_reports_payouts_restricted() -> None:
    decision = compute_financial_eligibility(
        status=OnboardingStatus.RESTRICTED,
        charges_enabled=True,
        payouts_enabled=False,
        requirements_due=False,
    )
    assert decision.eligible is False
    assert FinancialEligibilityReason.PAYOUTS_RESTRICTED in decision.reasons


def test_eligibility_disabled_reports_account_disabled() -> None:
    decision = compute_financial_eligibility(
        status=OnboardingStatus.DISABLED,
        charges_enabled=False,
        payouts_enabled=False,
        requirements_due=False,
    )
    assert decision.eligible is False
    assert FinancialEligibilityReason.ACCOUNT_DISABLED in decision.reasons
