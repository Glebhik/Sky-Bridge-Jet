"""Stripe test-mode payment adapter implementing the provider-neutral port.

Uses the separate-charge-and-transfer candidate: the customer is charged on the
platform account with manual capture; operator transfer/payout is a deferred
boundary. The adapter maps normalized gateway views to provider-neutral results
and never leaks raw Stripe objects. It stays an ADAPTER — not the domain.
"""

from __future__ import annotations

from sky_bridge_jet.core.stripe_gateway import StripeGateway
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind
from sky_bridge_jet.modules.payments.provider import (
    ClientAction,
    PaymentProviderError,
    ProviderErrorCategory,
    ProviderOutcome,
    ProviderResult,
)

# Stripe PaymentIntent statuses, mapped to provider-neutral outcomes.
_AUTHORIZED_STATUS = "requires_capture"
_CAPTURED_STATUS = "succeeded"
_REQUIRES_ACTION_STATUS = "requires_action"
_CANCELLED_STATUS = "canceled"
_REFUND_OK_STATUSES = frozenset({"succeeded", "pending"})


class StripeConnectPaymentProvider:
    """Provider-neutral payment adapter backed by Stripe test mode."""

    kind = PaymentProviderKind.STRIPE

    def __init__(self, gateway: StripeGateway) -> None:
        self._gateway = gateway

    def authorize(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_reference: str | None,
        idempotency_key: str,
    ) -> ProviderResult:
        try:
            intent = self._gateway.create_payment_intent(
                amount_minor=amount_minor,
                currency=currency,
                payment_method_reference=payment_method_reference,
                idempotency_key=f"authorize:{idempotency_key}",
            )
        except PaymentProviderError as error:
            if error.category is ProviderErrorCategory.PROVIDER_DECLINED:
                return ProviderResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_reference=None,
                    failure_code="authorization_declined",
                )
            raise

        if intent.status == _REQUIRES_ACTION_STATUS:
            action = (
                ClientAction(action_type="stripe_handle_next_action", client_secret=secret)
                if (secret := intent.client_secret) is not None
                else None
            )
            return ProviderResult(
                outcome=ProviderOutcome.REQUIRES_ACTION,
                provider_reference=intent.id,
                provider_status=intent.status,
                client_action=action,
            )
        if intent.status in (_AUTHORIZED_STATUS, _CAPTURED_STATUS):
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_reference=intent.id,
                provider_status=intent.status,
            )
        return ProviderResult(
            outcome=ProviderOutcome.FAILED,
            provider_reference=intent.id,
            failure_code="authorization_incomplete",
            provider_status=intent.status,
        )

    def capture(
        self, *, provider_reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> ProviderResult:
        try:
            intent = self._gateway.capture_payment_intent(
                intent_id=provider_reference, idempotency_key=f"capture:{idempotency_key}"
            )
        except PaymentProviderError as error:
            if error.category is ProviderErrorCategory.PROVIDER_DECLINED:
                return ProviderResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_reference=provider_reference,
                    failure_code="capture_declined",
                )
            raise
        if intent.status == _CAPTURED_STATUS:
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_reference=intent.id,
                provider_status=intent.status,
            )
        return ProviderResult(
            outcome=ProviderOutcome.FAILED,
            provider_reference=intent.id,
            failure_code="capture_incomplete",
            provider_status=intent.status,
        )

    def void(self, *, provider_reference: str, idempotency_key: str) -> ProviderResult:
        intent = self._gateway.cancel_payment_intent(
            intent_id=provider_reference, idempotency_key=f"void:{idempotency_key}"
        )
        outcome = (
            ProviderOutcome.SUCCEEDED
            if intent.status == _CANCELLED_STATUS
            else ProviderOutcome.FAILED
        )
        return ProviderResult(
            outcome=outcome, provider_reference=intent.id, provider_status=intent.status
        )

    def refund(
        self, *, provider_reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> ProviderResult:
        try:
            refund = self._gateway.create_refund(
                intent_id=provider_reference,
                amount_minor=amount_minor,
                idempotency_key=f"refund:{idempotency_key}",
            )
        except PaymentProviderError as error:
            if error.category is ProviderErrorCategory.PROVIDER_DECLINED:
                return ProviderResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_reference=provider_reference,
                    failure_code="refund_declined",
                )
            raise
        if refund.status in _REFUND_OK_STATUSES:
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_reference=refund.id,
                provider_status=refund.status,
            )
        return ProviderResult(
            outcome=ProviderOutcome.FAILED,
            provider_reference=refund.id,
            failure_code="refund_incomplete",
            provider_status=refund.status,
        )
