from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from sky_bridge_jet.modules.core_aviation.domain import DomainError


class OnboardingStatus(StrEnum):
    """Provider-neutral operator financial-onboarding lifecycle.

    This is distinct from Phase 6 aviation marketplace admission and never mirrors
    a provider's internal state one-for-one; provider capability state is
    translated into these stable domain states.
    """

    NOT_STARTED = "NOT_STARTED"
    ONBOARDING_PENDING = "ONBOARDING_PENDING"
    REQUIREMENTS_DUE = "REQUIREMENTS_DUE"
    UNDER_REVIEW = "UNDER_REVIEW"
    ENABLED = "ENABLED"
    RESTRICTED = "RESTRICTED"
    DISABLED = "DISABLED"


class FinancialEligibilityReason(StrEnum):
    NO_CONNECTED_ACCOUNT = "NO_CONNECTED_ACCOUNT"
    ONBOARDING_INCOMPLETE = "ONBOARDING_INCOMPLETE"
    REQUIREMENTS_DUE = "REQUIREMENTS_DUE"
    CHARGES_DISABLED = "CHARGES_DISABLED"
    PAYOUTS_RESTRICTED = "PAYOUTS_RESTRICTED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"


class WebhookProcessingStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"


class FinancialConflictError(DomainError):
    """Base for financial-onboarding conflicts (maps to 409)."""

    code = "financial_conflict"


class ConnectedAccountConflictError(FinancialConflictError):
    """Raised when a connected account already exists for the operator/provider."""

    code = "connected_account_exists"


@dataclass(frozen=True)
class ProviderAccountSnapshot:
    """Normalized provider capability snapshot used to derive domain state."""

    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    requirements_due: bool
    disabled_reason: str | None


@dataclass
class FinancialEligibilityDecision:
    eligible: bool
    reasons: list[FinancialEligibilityReason] = field(default_factory=list)


# Statuses in which the operator can participate in PSP-enabled payment flows.
_ELIGIBLE_STATUSES: Final[frozenset[OnboardingStatus]] = frozenset({OnboardingStatus.ENABLED})


def derive_onboarding_status(snapshot: ProviderAccountSnapshot) -> OnboardingStatus:
    """Translate a provider capability snapshot into a stable domain status."""
    if snapshot.disabled_reason and not snapshot.charges_enabled:
        return OnboardingStatus.DISABLED
    if snapshot.charges_enabled and snapshot.payouts_enabled:
        return OnboardingStatus.ENABLED
    if snapshot.charges_enabled and not snapshot.payouts_enabled:
        return OnboardingStatus.RESTRICTED
    if snapshot.requirements_due:
        return OnboardingStatus.REQUIREMENTS_DUE
    if snapshot.details_submitted:
        return OnboardingStatus.UNDER_REVIEW
    return OnboardingStatus.ONBOARDING_PENDING


def compute_financial_eligibility(
    *,
    status: OnboardingStatus | None,
    charges_enabled: bool,
    payouts_enabled: bool,
    requirements_due: bool,
) -> FinancialEligibilityDecision:
    """Explainable financial eligibility for PSP-enabled payment flows.

    Requiring ENABLED (charges and payouts) is Sky Bridge Jet's configured Phase 7
    policy, not a legal or provider guarantee. This is separate from aviation
    marketplace eligibility.
    """
    if status is None:
        return FinancialEligibilityDecision(
            eligible=False, reasons=[FinancialEligibilityReason.NO_CONNECTED_ACCOUNT]
        )
    if status in _ELIGIBLE_STATUSES:
        return FinancialEligibilityDecision(eligible=True, reasons=[])

    reasons: list[FinancialEligibilityReason] = []
    if status is OnboardingStatus.DISABLED:
        reasons.append(FinancialEligibilityReason.ACCOUNT_DISABLED)
    if not charges_enabled and status is not OnboardingStatus.DISABLED:
        reasons.append(FinancialEligibilityReason.CHARGES_DISABLED)
    if status is OnboardingStatus.RESTRICTED or (charges_enabled and not payouts_enabled):
        reasons.append(FinancialEligibilityReason.PAYOUTS_RESTRICTED)
    if requirements_due:
        reasons.append(FinancialEligibilityReason.REQUIREMENTS_DUE)
    if status in {
        OnboardingStatus.NOT_STARTED,
        OnboardingStatus.ONBOARDING_PENDING,
        OnboardingStatus.UNDER_REVIEW,
    }:
        reasons.append(FinancialEligibilityReason.ONBOARDING_INCOMPLETE)
    if not reasons:
        reasons.append(FinancialEligibilityReason.ONBOARDING_INCOMPLETE)
    return FinancialEligibilityDecision(eligible=False, reasons=reasons)
