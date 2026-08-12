from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.core.stripe_gateway import StripeGateway, build_stripe_gateway
from sky_bridge_jet.modules.financials.domain import ProviderAccountSnapshot
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind


@dataclass(frozen=True)
class ConnectedAccountCreation:
    account_reference: str
    country: str | None
    snapshot: ProviderAccountSnapshot


@dataclass(frozen=True)
class OnboardingLink:
    """Ephemeral onboarding URL. Never persisted or logged."""

    url: str
    expires_at: int


class FinancialConnectProvider(Protocol):
    """Provider-neutral operator financial-onboarding port."""

    kind: PaymentProviderKind

    def create_account(self, *, country: str, idempotency_key: str) -> ConnectedAccountCreation: ...

    def create_onboarding_link(self, *, account_reference: str) -> OnboardingLink: ...

    def retrieve_account(self, *, account_reference: str) -> ProviderAccountSnapshot: ...


_PENDING_SNAPSHOT = ProviderAccountSnapshot(
    charges_enabled=False,
    payouts_enabled=False,
    details_submitted=False,
    requirements_due=True,
    disabled_reason=None,
)


class FakeFinancialConnectProvider:
    """Deterministic, in-process fake. NOT A PRODUCTION INTEGRATION; no network.

    ``retrieve_snapshot`` lets tests control the capability state returned by a
    synchronization call.
    """

    kind = PaymentProviderKind.FAKE

    def __init__(self, retrieve_snapshot: ProviderAccountSnapshot | None = None) -> None:
        self._retrieve_snapshot = retrieve_snapshot

    def create_account(self, *, country: str, idempotency_key: str) -> ConnectedAccountCreation:
        return ConnectedAccountCreation(
            account_reference=f"acct_fake_{secrets.token_hex(8)}",
            country=country,
            snapshot=_PENDING_SNAPSHOT,
        )

    def create_onboarding_link(self, *, account_reference: str) -> OnboardingLink:
        return OnboardingLink(
            url=f"https://connect.fake.invalid/onboarding/{account_reference}",
            expires_at=0,
        )

    def retrieve_account(self, *, account_reference: str) -> ProviderAccountSnapshot:
        return self._retrieve_snapshot or _PENDING_SNAPSHOT


class StripeConnectFinancialProvider:
    """Stripe test-mode connected-account adapter behind the provider-neutral port."""

    kind = PaymentProviderKind.STRIPE

    def __init__(self, gateway: StripeGateway) -> None:
        self._gateway = gateway

    @staticmethod
    def _snapshot(view: object) -> ProviderAccountSnapshot:
        return ProviderAccountSnapshot(
            charges_enabled=view.charges_enabled,  # type: ignore[attr-defined]
            payouts_enabled=view.payouts_enabled,  # type: ignore[attr-defined]
            details_submitted=view.details_submitted,  # type: ignore[attr-defined]
            requirements_due=view.requirements_due,  # type: ignore[attr-defined]
            disabled_reason=view.disabled_reason,  # type: ignore[attr-defined]
        )

    def create_account(self, *, country: str, idempotency_key: str) -> ConnectedAccountCreation:
        view = self._gateway.create_connected_account(
            country=country, idempotency_key=f"account:{idempotency_key}"
        )
        return ConnectedAccountCreation(
            account_reference=view.id, country=view.country, snapshot=self._snapshot(view)
        )

    def create_onboarding_link(self, *, account_reference: str) -> OnboardingLink:
        link = self._gateway.create_account_link(account_id=account_reference)
        return OnboardingLink(url=link.url, expires_at=link.expires_at)

    def retrieve_account(self, *, account_reference: str) -> ProviderAccountSnapshot:
        view = self._gateway.retrieve_account(account_id=account_reference)
        return self._snapshot(view)


def get_financial_connect_provider(settings: Settings) -> FinancialConnectProvider:
    """Return the active connect provider (Stripe when enabled, else the fake)."""
    if settings.stripe_enabled:
        return StripeConnectFinancialProvider(build_stripe_gateway(settings.stripe_secret_key))
    return FakeFinancialConnectProvider()
