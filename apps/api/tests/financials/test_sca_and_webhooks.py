"""SCA (requires-customer-action) and the verified, idempotent webhook pipeline.

These prove: an authorize can land in a provider-neutral REQUIRES_CUSTOMER_ACTION
state that returns a safe client action; a later verified webhook advances the
payment; and duplicate / out-of-order deliveries never double-apply or regress
state. The Stripe boundary is faked, so no network or signing secret is needed.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.main import app
from sky_bridge_jet.modules.financials.provider import StripeConnectFinancialProvider
from sky_bridge_jet.modules.financials.reconciliation import (
    NormalizedProviderEvent,
    WebhookReconciliationService,
)
from sky_bridge_jet.modules.financials.router import (
    StripeWebhookContext,
    get_stripe_webhook_context,
)
from sky_bridge_jet.modules.financials.services import FinancialOnboardingService
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind, PaymentStatus
from sky_bridge_jet.modules.payments.models import Payment
from sky_bridge_jet.modules.payments.schemas import PaymentAuthorize
from sky_bridge_jet.modules.payments.services import PaymentService
from sky_bridge_jet.modules.payments.stripe_adapter import StripeConnectPaymentProvider

from ._support import (
    ENABLED_ACCOUNT,
    VALID_SIGNATURE,
    FakeStripeGateway,
    booking_scenario,
    requires_db,
    signed_event,
    stripe_test_settings,
)


def _key() -> str:
    return f"idem-{uuid4()}"


def _onboard(operator_id: str) -> None:
    with SessionLocal() as session:
        FinancialOnboardingService(
            session,
            connect_provider=StripeConnectFinancialProvider(
                FakeStripeGateway(account=ENABLED_ACCOUNT)
            ),
            settings=stripe_test_settings(),
        ).create_account(UUID(operator_id))


def _sca_payment(client: TestClient, airports: list, intent_id: str) -> tuple[str, str]:
    """Create an onboarded Stripe payment and authorize it into SCA. Return ids."""
    scenario = booking_scenario(client, airports)
    _onboard(scenario["operator"]["id"])
    gateway = FakeStripeGateway(
        intent_status="requires_action", next_intent_id=intent_id, client_secret="pi_secret_xyz"
    )
    with SessionLocal() as session:
        service = PaymentService(
            session,
            provider=StripeConnectPaymentProvider(gateway),
            settings=stripe_test_settings(),
        )
        payment = service.create_for_booking(UUID(scenario["booking"]["id"]))
        payment_id = str(payment.id)
        authorized = service.authorize(
            payment.id,
            PaymentAuthorize(idempotency_key=_key(), payment_method_reference="pm_card"),
        )
        assert authorized.requires_customer_action is True
        assert authorized.client_action is not None
        assert authorized.client_action.client_secret == "pi_secret_xyz"
    return payment_id, intent_id


def _payment_row(session, payment_id: str) -> Payment:
    row = session.get(Payment, UUID(payment_id))
    assert row is not None
    return row


@requires_db
def test_authorize_requires_action_keeps_payment_created(
    client: TestClient, airports: list
) -> None:
    payment_id, _ = _sca_payment(client, airports, f"pi_sca_{uuid4().hex[:10]}")
    with SessionLocal() as session:
        row = _payment_row(session, payment_id)
        assert row.status is PaymentStatus.CREATED
        assert row.requires_customer_action is True
        assert row.payment_provider is PaymentProviderKind.STRIPE


@requires_db
def test_webhook_authorized_event_advances_payment(client: TestClient, airports: list) -> None:
    intent_id = f"pi_auth_{uuid4().hex[:10]}"
    payment_id, provider_ref = _sca_payment(client, airports, intent_id)
    event = NormalizedProviderEvent(
        provider=PaymentProviderKind.STRIPE,
        event_id=f"evt_{uuid4().hex}",
        event_type="payment_intent.amount_capturable_updated",
        object_id=provider_ref,
        data={"status": "requires_capture"},
    )
    with SessionLocal() as session:
        result = WebhookReconciliationService(session).process(event)
        assert result.duplicate is False
    with SessionLocal() as session:
        row = _payment_row(session, payment_id)
        assert row.status is PaymentStatus.AUTHORIZED
        assert row.requires_customer_action is False


@requires_db
def test_duplicate_webhook_is_idempotent(client: TestClient, airports: list) -> None:
    intent_id = f"pi_dup_{uuid4().hex[:10]}"
    payment_id, provider_ref = _sca_payment(client, airports, intent_id)
    event = NormalizedProviderEvent(
        provider=PaymentProviderKind.STRIPE,
        event_id=f"evt_{uuid4().hex}",
        event_type="payment_intent.amount_capturable_updated",
        object_id=provider_ref,
        data={"status": "requires_capture"},
    )
    with SessionLocal() as session:
        first = WebhookReconciliationService(session).process(event)
        assert first.duplicate is False
    with SessionLocal() as session:
        second = WebhookReconciliationService(session).process(event)
        assert second.duplicate is True
    with SessionLocal() as session:
        # Still exactly one authorization; the duplicate did not re-apply.
        row = _payment_row(session, payment_id)
        assert row.status is PaymentStatus.AUTHORIZED
        assert row.authorized_amount_minor == row.total_amount_minor


@requires_db
def test_out_of_order_capture_before_authorize_is_ignored(
    client: TestClient, airports: list
) -> None:
    intent_id = f"pi_ooo_{uuid4().hex[:10]}"
    payment_id, provider_ref = _sca_payment(client, airports, intent_id)

    captured_event = NormalizedProviderEvent(
        provider=PaymentProviderKind.STRIPE,
        event_id=f"evt_{uuid4().hex}",
        event_type="payment_intent.succeeded",
        object_id=provider_ref,
        data={"status": "succeeded"},
    )
    with SessionLocal() as session:
        WebhookReconciliationService(session).process(captured_event)
    with SessionLocal() as session:
        # A capture cannot land before the authorization does; state is unchanged.
        row = _payment_row(session, payment_id)
        assert row.status is PaymentStatus.CREATED
        assert row.captured_amount_minor == 0

    authorized_event = NormalizedProviderEvent(
        provider=PaymentProviderKind.STRIPE,
        event_id=f"evt_{uuid4().hex}",
        event_type="payment_intent.amount_capturable_updated",
        object_id=provider_ref,
        data={"status": "requires_capture"},
    )
    with SessionLocal() as session:
        WebhookReconciliationService(session).process(authorized_event)
    with SessionLocal() as session:
        row = _payment_row(session, payment_id)
        assert row.status is PaymentStatus.AUTHORIZED


@requires_db
def test_webhook_endpoint_verifies_signature(client: TestClient, airports: list) -> None:
    app.dependency_overrides[get_stripe_webhook_context] = lambda: StripeWebhookContext(
        gateway=FakeStripeGateway(), webhook_secret="whsec_test"
    )
    try:
        body = signed_event(
            f"evt_{uuid4().hex}", "account.updated", "acct_unknown", charges_enabled=True
        )
        ok = client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": VALID_SIGNATURE},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["received"] is True

        invalid = client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": "t=1,v1=tampered"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "invalid_webhook_signature"

        missing = client.post("/api/v1/webhooks/stripe", content=body)
        assert missing.status_code == 400
    finally:
        app.dependency_overrides.pop(get_stripe_webhook_context, None)


@requires_db
def test_webhook_endpoint_duplicate_ack(client: TestClient, airports: list) -> None:
    app.dependency_overrides[get_stripe_webhook_context] = lambda: StripeWebhookContext(
        gateway=FakeStripeGateway(), webhook_secret="whsec_test"
    )
    try:
        event_id = f"evt_{uuid4().hex}"
        body = signed_event(event_id, "account.updated", "acct_unknown", charges_enabled=True)
        headers = {"Stripe-Signature": VALID_SIGNATURE}
        first = client.post("/api/v1/webhooks/stripe", content=body, headers=headers)
        second = client.post("/api/v1/webhooks/stripe", content=body, headers=headers)
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
    finally:
        app.dependency_overrides.pop(get_stripe_webhook_context, None)
