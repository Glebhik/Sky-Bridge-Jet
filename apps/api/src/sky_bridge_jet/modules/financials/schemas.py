from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sky_bridge_jet.modules.financials.domain import (
    FinancialEligibilityReason,
    OnboardingStatus,
    WebhookProcessingStatus,
)
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConnectedAccountResponse(ApiModel):
    id: UUID
    operator_id: UUID
    payment_provider: PaymentProviderKind
    provider_account_reference: str
    onboarding_status: OnboardingStatus
    charges_enabled: bool
    payouts_enabled: bool
    requirements_due: bool
    account_country: str | None
    disabled_reason: str | None
    created_at: datetime
    synchronized_at: datetime | None


class OnboardingLinkResponse(ApiModel):
    url: str
    expires_at: int


class FinancialEligibilityResponse(ApiModel):
    operator_id: UUID
    eligible: bool
    reasons: list[FinancialEligibilityReason]


class WebhookAckResponse(ApiModel):
    received: bool
    status: WebhookProcessingStatus
    duplicate: bool
