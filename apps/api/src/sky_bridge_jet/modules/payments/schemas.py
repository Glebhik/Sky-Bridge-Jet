from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sky_bridge_jet.modules.payments.domain import (
    PaymentOperationResult,
    PaymentProviderKind,
    PaymentStatus,
    SettlementEligibility,
)

# Idempotency keys are opaque, bounded, client-supplied, and never logged.
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=200)]
# A tokenized payment-method reference from a future PSP-hosted field. Transient
# input only — never persisted. Never a PAN, CVV, or raw credential.
PaymentMethodReference = Annotated[str, Field(min_length=1, max_length=200)]
RefundAmount = Annotated[int, Field(ge=1, le=10**15)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaymentAuthorize(ApiModel):
    idempotency_key: IdempotencyKey
    payment_method_reference: PaymentMethodReference | None = None


class PaymentCapture(ApiModel):
    idempotency_key: IdempotencyKey


class PaymentVoid(ApiModel):
    idempotency_key: IdempotencyKey


class RefundCreate(ApiModel):
    idempotency_key: IdempotencyKey
    amount_minor: RefundAmount


class ClientActionResponse(ApiModel):
    """SCA challenge metadata for the client SDK to complete an action.

    Returned once on the authorize response when the payment requires customer
    action. The ``client_secret`` is provider-issued for the client SDK and is
    never persisted or logged server-side.
    """

    action_type: str
    client_secret: str


class PaymentResponse(ApiModel):
    id: UUID
    reference: str
    booking_id: UUID
    status: PaymentStatus
    currency: str
    payment_provider: PaymentProviderKind
    operator_amount_minor: int
    platform_fee_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    authorized_amount_minor: int | None
    captured_amount_minor: int
    refunded_amount_minor: int
    provider_payment_reference: str | None
    provider_status: str | None
    requires_customer_action: bool
    authorized_at: datetime | None
    captured_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Present only on an authorize response that triggered an SCA challenge.
    client_action: ClientActionResponse | None = None


class RefundResponse(ApiModel):
    id: UUID
    payment_id: UUID
    amount_minor: int
    currency: str
    result: PaymentOperationResult
    provider_reference: str | None
    failure_code: str | None
    created_at: datetime


class AllocationResponse(ApiModel):
    payment_id: UUID
    booking_id: UUID
    currency: str
    operator_amount_minor: int
    platform_fee_minor: int
    tax_amount_minor: int
    total_customer_amount_minor: int
    captured_amount_minor: int
    refunded_amount_minor: int
    settlement_eligibility: SettlementEligibility
