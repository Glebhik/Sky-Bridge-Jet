"""Adapter-level tests: real Stripe adapters mapping a mocked gateway boundary.

No Stripe SDK or network is involved — the adapters run against
:class:`FakeStripeGateway`, so this proves the mapping logic (statuses, SCA,
error categories, idempotency-key prefixing) without external dependencies.
"""

from __future__ import annotations

import pytest

from sky_bridge_jet.modules.financials.domain import OnboardingStatus
from sky_bridge_jet.modules.financials.provider import StripeConnectFinancialProvider
from sky_bridge_jet.modules.payments.provider import (
    PaymentProviderError,
    PaymentProviderKind,
    ProviderErrorCategory,
    ProviderOutcome,
)
from sky_bridge_jet.modules.payments.stripe_adapter import StripeConnectPaymentProvider

from ._support import ENABLED_ACCOUNT, FakeStripeGateway


def test_adapter_kind_is_stripe() -> None:
    assert StripeConnectPaymentProvider(FakeStripeGateway()).kind is PaymentProviderKind.STRIPE


def test_authorize_success_maps_requires_capture() -> None:
    provider = StripeConnectPaymentProvider(FakeStripeGateway(intent_status="requires_capture"))
    result = provider.authorize(
        amount_minor=1000, currency="EUR", payment_method_reference="pm_x", idempotency_key="k1"
    )
    assert result.outcome is ProviderOutcome.SUCCEEDED
    assert result.provider_reference == "pi_test_123"
    assert result.provider_status == "requires_capture"
    assert result.client_action is None


def test_authorize_requires_action_returns_client_action() -> None:
    gateway = FakeStripeGateway(intent_status="requires_action", client_secret="pi_secret_abc")
    provider = StripeConnectPaymentProvider(gateway)
    result = provider.authorize(
        amount_minor=1000, currency="EUR", payment_method_reference="pm_x", idempotency_key="k2"
    )
    assert result.outcome is ProviderOutcome.REQUIRES_ACTION
    assert result.client_action is not None
    assert result.client_action.client_secret == "pi_secret_abc"
    # Idempotency keys are namespaced per operation.
    assert ("create_payment_intent", "authorize:k2") in gateway.calls


def test_authorize_declined_maps_to_failed_result() -> None:
    class DecliningGateway(FakeStripeGateway):
        def create_payment_intent(self, **_kwargs: object):  # type: ignore[override]
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_DECLINED)

    provider = StripeConnectPaymentProvider(DecliningGateway())
    result = provider.authorize(
        amount_minor=1000, currency="EUR", payment_method_reference="pm_x", idempotency_key="k3"
    )
    assert result.outcome is ProviderOutcome.FAILED
    assert result.failure_code == "authorization_declined"


def test_authorize_infrastructure_error_propagates() -> None:
    class UnavailableGateway(FakeStripeGateway):
        def create_payment_intent(self, **_kwargs: object):  # type: ignore[override]
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE)

    provider = StripeConnectPaymentProvider(UnavailableGateway())
    with pytest.raises(PaymentProviderError) as error:
        provider.authorize(
            amount_minor=1000, currency="EUR", payment_method_reference=None, idempotency_key="k4"
        )
    assert error.value.category is ProviderErrorCategory.PROVIDER_UNAVAILABLE


def test_capture_success_and_incomplete() -> None:
    ok = StripeConnectPaymentProvider(FakeStripeGateway(capture_status="succeeded"))
    assert (
        ok.capture(
            provider_reference="pi_1", amount_minor=1000, currency="EUR", idempotency_key="c1"
        ).outcome
        is ProviderOutcome.SUCCEEDED
    )
    incomplete = StripeConnectPaymentProvider(FakeStripeGateway(capture_status="processing"))
    assert (
        incomplete.capture(
            provider_reference="pi_1", amount_minor=1000, currency="EUR", idempotency_key="c2"
        ).outcome
        is ProviderOutcome.FAILED
    )


def test_void_and_refund_mapping() -> None:
    provider = StripeConnectPaymentProvider(FakeStripeGateway())
    assert (
        provider.void(provider_reference="pi_1", idempotency_key="v1").outcome
        is ProviderOutcome.SUCCEEDED
    )
    refund = provider.refund(
        provider_reference="pi_1", amount_minor=500, currency="EUR", idempotency_key="r1"
    )
    assert refund.outcome is ProviderOutcome.SUCCEEDED


def test_financial_provider_maps_account_snapshot() -> None:
    from sky_bridge_jet.modules.financials.domain import derive_onboarding_status

    provider = StripeConnectFinancialProvider(FakeStripeGateway(account=ENABLED_ACCOUNT))
    creation = provider.create_account(country="IE", idempotency_key="op-1")
    assert creation.account_reference.startswith("acct_")
    assert creation.snapshot.charges_enabled is True
    assert derive_onboarding_status(creation.snapshot) is OnboardingStatus.ENABLED
