"""The financial-onboarding gate for PSP-backed payments (service-level, DB-backed).

A Stripe-backed payment must require the operator to be financially onboarded, and
this gate is *separate from and additive to* Phase 6 aviation eligibility — it never
mutates aviation compliance state and never weakens the aviation gates.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.financials.provider import StripeConnectFinancialProvider
from sky_bridge_jet.modules.financials.services import FinancialOnboardingService
from sky_bridge_jet.modules.payments.domain import PaymentEligibilityError, PaymentProviderKind
from sky_bridge_jet.modules.payments.services import PaymentService
from sky_bridge_jet.modules.payments.stripe_adapter import StripeConnectPaymentProvider

from ._support import (
    ENABLED_ACCOUNT,
    REQUIREMENTS_DUE_ACCOUNT,
    FakeStripeGateway,
    booking_scenario,
    requires_db,
    stripe_test_settings,
)


def _onboard(operator_id: str, account) -> None:
    with SessionLocal() as session:
        FinancialOnboardingService(
            session,
            connect_provider=StripeConnectFinancialProvider(FakeStripeGateway(account=account)),
            settings=stripe_test_settings(),
        ).create_account(UUID(operator_id))


def _stripe_payment_service(session) -> PaymentService:
    return PaymentService(
        session,
        provider=StripeConnectPaymentProvider(FakeStripeGateway()),
        settings=stripe_test_settings(),
    )


@requires_db
def test_stripe_payment_blocked_when_not_financially_onboarded(
    client: TestClient, airports: list
) -> None:
    scenario = booking_scenario(client, airports)
    with SessionLocal() as session:
        with pytest.raises(PaymentEligibilityError):
            _stripe_payment_service(session).create_for_booking(UUID(scenario["booking"]["id"]))


@requires_db
def test_stripe_payment_blocked_when_requirements_due(client: TestClient, airports: list) -> None:
    scenario = booking_scenario(client, airports)
    _onboard(scenario["operator"]["id"], REQUIREMENTS_DUE_ACCOUNT)
    with SessionLocal() as session:
        with pytest.raises(PaymentEligibilityError):
            _stripe_payment_service(session).create_for_booking(UUID(scenario["booking"]["id"]))


@requires_db
def test_stripe_payment_permitted_when_onboarded(client: TestClient, airports: list) -> None:
    scenario = booking_scenario(client, airports)
    _onboard(scenario["operator"]["id"], ENABLED_ACCOUNT)
    with SessionLocal() as session:
        payment = _stripe_payment_service(session).create_for_booking(
            UUID(scenario["booking"]["id"])
        )
        assert payment.payment_provider is PaymentProviderKind.STRIPE
        assert payment.status.value == "CREATED"


@requires_db
def test_fake_payment_path_unaffected_by_financial_gate(client: TestClient, airports: list) -> None:
    # The default (fake) provider needs no financial onboarding — Phase 5 behavior
    # is fully preserved and never touches Stripe.
    scenario = booking_scenario(client, airports)
    with SessionLocal() as session:
        payment = PaymentService(session).create_for_booking(UUID(scenario["booking"]["id"]))
        assert payment.payment_provider is PaymentProviderKind.FAKE


@requires_db
def test_financial_onboarding_does_not_change_aviation_admission(
    client: TestClient, airports: list
) -> None:
    scenario = booking_scenario(client, airports)
    operator_id = scenario["operator"]["id"]
    before = client.get(f"/api/v1/operators/{operator_id}/admission").json()
    _onboard(operator_id, ENABLED_ACCOUNT)
    after = client.get(f"/api/v1/operators/{operator_id}/admission").json()
    # Financial onboarding is a distinct domain; aviation admission is untouched.
    assert before["status"] == after["status"]
