"""Thin, injectable seam over the Stripe SDK.

The seam lets the payment/onboarding adapters run against a deterministic fake in
tests — no network, no credentials — while production uses ``RealStripeGateway``.
Raw Stripe objects and exceptions never cross this boundary: methods return
normalized views or raise :class:`PaymentProviderError` /
:class:`WebhookSignatureError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sky_bridge_jet.modules.payments.provider import (
    PaymentProviderError,
    ProviderErrorCategory,
)


class WebhookSignatureError(Exception):
    """Raised when a provider webhook signature cannot be verified."""


@dataclass(frozen=True)
class StripePaymentIntentView:
    id: str
    status: str
    client_secret: str | None = None


@dataclass(frozen=True)
class StripeRefundView:
    id: str
    status: str


@dataclass(frozen=True)
class StripeAccountView:
    id: str
    country: str | None
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    requirements_due: bool
    disabled_reason: str | None


@dataclass(frozen=True)
class StripeAccountLinkView:
    url: str
    expires_at: int


@dataclass(frozen=True)
class StripeEventView:
    id: str
    type: str
    object_id: str | None
    data: dict[str, Any] = field(default_factory=dict)


class StripeGateway(Protocol):
    """Provider-neutral surface the adapters depend on (never the raw SDK)."""

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_reference: str | None,
        idempotency_key: str,
    ) -> StripePaymentIntentView: ...

    def capture_payment_intent(
        self, *, intent_id: str, idempotency_key: str
    ) -> StripePaymentIntentView: ...

    def cancel_payment_intent(
        self, *, intent_id: str, idempotency_key: str
    ) -> StripePaymentIntentView: ...

    def create_refund(
        self, *, intent_id: str, amount_minor: int, idempotency_key: str
    ) -> StripeRefundView: ...

    def create_connected_account(
        self, *, country: str, idempotency_key: str
    ) -> StripeAccountView: ...

    def create_account_link(self, *, account_id: str) -> StripeAccountLinkView: ...

    def retrieve_account(self, *, account_id: str) -> StripeAccountView: ...

    def construct_webhook_event(
        self, *, payload: bytes, signature_header: str | None, webhook_secret: str
    ) -> StripeEventView: ...


class RealStripeGateway:
    """Production gateway backed by the official Stripe SDK (test-mode keys only).

    All SDK exceptions are converted to provider-neutral errors; no raw provider
    payload, key, or request id is surfaced.
    """

    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key

    def _stripe(self) -> Any:
        try:
            import stripe
        except ImportError as error:  # pragma: no cover - dependency is pinned
            raise PaymentProviderError(
                ProviderErrorCategory.PROVIDER_CONFIGURATION_ERROR,
                "Stripe SDK is not available",
            ) from error
        stripe.api_key = self._secret_key
        return stripe

    def _call(self, fn: Any) -> Any:
        stripe = self._stripe()
        try:
            return fn(stripe)
        except stripe.error.CardError as error:  # decline
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_DECLINED) from error
        except stripe.error.AuthenticationError as error:
            raise PaymentProviderError(
                ProviderErrorCategory.PROVIDER_AUTHENTICATION_ERROR
            ) from error
        except stripe.error.InvalidRequestError as error:
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_INVALID_STATE) from error
        except (stripe.error.APIConnectionError, stripe.error.APIError) as error:
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE) from error
        except stripe.error.StripeError as error:
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_INVALID_STATE) from error

    @staticmethod
    def _intent_view(intent: Any) -> StripePaymentIntentView:
        return StripePaymentIntentView(
            id=intent.id, status=intent.status, client_secret=getattr(intent, "client_secret", None)
        )

    @staticmethod
    def _account_view(account: Any) -> StripeAccountView:
        requirements = getattr(account, "requirements", None) or {}
        currently_due = (requirements.get("currently_due") if requirements else None) or []
        return StripeAccountView(
            id=account.id,
            country=getattr(account, "country", None),
            charges_enabled=bool(getattr(account, "charges_enabled", False)),
            payouts_enabled=bool(getattr(account, "payouts_enabled", False)),
            details_submitted=bool(getattr(account, "details_submitted", False)),
            requirements_due=bool(currently_due),
            disabled_reason=(requirements.get("disabled_reason") if requirements else None),
        )

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_reference: str | None,
        idempotency_key: str,
    ) -> StripePaymentIntentView:
        params: dict[str, Any] = {
            "amount": amount_minor,
            "currency": currency.lower(),
            "capture_method": "manual",
            "confirm": payment_method_reference is not None,
            "automatic_payment_methods": {"enabled": True},
            # Opaque operation correlation only: no customer, passenger, or
            # commercial-detail metadata crosses the provider boundary.
            "metadata": {"operation_correlation": idempotency_key},
        }
        if payment_method_reference is not None:
            params["payment_method"] = payment_method_reference
        intent = self._call(
            lambda s: s.PaymentIntent.create(idempotency_key=idempotency_key, **params)
        )
        return self._intent_view(intent)

    def capture_payment_intent(
        self, *, intent_id: str, idempotency_key: str
    ) -> StripePaymentIntentView:
        intent = self._call(
            lambda s: s.PaymentIntent.capture(intent_id, idempotency_key=idempotency_key)
        )
        return self._intent_view(intent)

    def cancel_payment_intent(
        self, *, intent_id: str, idempotency_key: str
    ) -> StripePaymentIntentView:
        intent = self._call(
            lambda s: s.PaymentIntent.cancel(intent_id, idempotency_key=idempotency_key)
        )
        return self._intent_view(intent)

    def create_refund(
        self, *, intent_id: str, amount_minor: int, idempotency_key: str
    ) -> StripeRefundView:
        refund = self._call(
            lambda s: s.Refund.create(
                payment_intent=intent_id, amount=amount_minor, idempotency_key=idempotency_key
            )
        )
        return StripeRefundView(id=refund.id, status=refund.status)

    def create_connected_account(self, *, country: str, idempotency_key: str) -> StripeAccountView:
        account = self._call(
            lambda s: s.Account.create(
                type="express", country=country, idempotency_key=idempotency_key
            )
        )
        return self._account_view(account)

    def create_account_link(self, *, account_id: str) -> StripeAccountLinkView:
        link = self._call(
            lambda s: s.AccountLink.create(
                account=account_id,
                type="account_onboarding",
                refresh_url="https://example.invalid/reauth",
                return_url="https://example.invalid/return",
            )
        )
        return StripeAccountLinkView(url=link.url, expires_at=int(link.expires_at))

    def retrieve_account(self, *, account_id: str) -> StripeAccountView:
        account = self._call(lambda s: s.Account.retrieve(account_id))
        return self._account_view(account)

    def construct_webhook_event(
        self, *, payload: bytes, signature_header: str | None, webhook_secret: str
    ) -> StripeEventView:
        stripe = self._stripe()
        if not signature_header:
            raise WebhookSignatureError("Missing webhook signature")
        try:
            event = stripe.Webhook.construct_event(payload, signature_header, webhook_secret)
        except stripe.error.SignatureVerificationError as error:
            raise WebhookSignatureError("Invalid webhook signature") from error
        except ValueError as error:
            raise WebhookSignatureError("Malformed webhook payload") from error
        data_object = (event.get("data") or {}).get("object") or {}
        return StripeEventView(
            id=event["id"],
            type=event["type"],
            object_id=data_object.get("id"),
            data=dict(data_object),
        )


def build_stripe_gateway(secret_key: str | None) -> StripeGateway:
    """Construct the production Stripe gateway; requires a configured secret key."""
    if not secret_key:
        raise PaymentProviderError(
            ProviderErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            "Stripe is enabled but no secret key is configured",
        )
    return RealStripeGateway(secret_key)
