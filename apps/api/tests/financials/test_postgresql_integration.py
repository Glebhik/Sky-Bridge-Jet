"""PostgreSQL-backed concurrency and large-value money tests for Phase 7.

Uniqueness of connected accounts and webhook events is DB-enforced; these tests
exercise the real constraints under concurrent access. Money stays integer minor
units at large magnitudes (no float).
"""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.financials.domain import ConnectedAccountConflictError
from sky_bridge_jet.modules.financials.models import (
    OperatorConnectedAccount,
    ProviderWebhookEvent,
)
from sky_bridge_jet.modules.financials.provider import StripeConnectFinancialProvider
from sky_bridge_jet.modules.financials.reconciliation import (
    NormalizedProviderEvent,
    WebhookReconciliationService,
)
from sky_bridge_jet.modules.financials.services import FinancialOnboardingService
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind, PaymentStatus
from sky_bridge_jet.modules.payments.models import Payment
from sky_bridge_jet.modules.payments.schemas import PaymentAuthorize, PaymentCapture
from sky_bridge_jet.modules.payments.services import PaymentService
from sky_bridge_jet.modules.payments.stripe_adapter import StripeConnectPaymentProvider

from ._support import (
    ENABLED_ACCOUNT,
    FakeStripeGateway,
    booking_scenario,
    requires_db,
    stripe_test_settings,
)


def _operator(client: TestClient) -> str:
    return client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Concurrent Ops {uuid4()}",
            "country_code": "IE",
            "contact_email": f"conc-{uuid4()}@example.test",
        },
    ).json()["id"]


def _onboarding_service(session) -> FinancialOnboardingService:
    return FinancialOnboardingService(
        session,
        connect_provider=StripeConnectFinancialProvider(FakeStripeGateway(account=ENABLED_ACCOUNT)),
        settings=stripe_test_settings(),
    )


@requires_db
def test_concurrent_account_creation_yields_one(client: TestClient, airports: list) -> None:
    operator_id = _operator(client)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                _onboarding_service(session).create_account(UUID(operator_id))
            result = "created"
        except ConnectedAccountConflictError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as session:
        rows = (
            session.query(OperatorConnectedAccount)
            .filter(OperatorConnectedAccount.operator_id == UUID(operator_id))
            .all()
        )
    assert len(rows) == 1
    assert outcomes.count("created") == 1
    assert outcomes.count("conflict") == 1


@requires_db
def test_concurrent_duplicate_webhook_processed_once(client: TestClient, airports: list) -> None:
    event_id = f"evt_{uuid4().hex}"
    event = NormalizedProviderEvent(
        provider=PaymentProviderKind.STRIPE,
        event_id=event_id,
        event_type="account.updated",
        object_id="acct_unknown",
        data={"charges_enabled": True},
    )
    barrier = threading.Barrier(2)
    duplicates: list[bool] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        with SessionLocal() as session:
            result = WebhookReconciliationService(session).process(event)
        with lock:
            duplicates.append(result.duplicate)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as session:
        rows = (
            session.query(ProviderWebhookEvent)
            .filter(ProviderWebhookEvent.provider_event_id == event_id)
            .all()
        )
    assert len(rows) == 1
    # Exactly one delivery did the work; the other observed a duplicate.
    assert duplicates.count(True) == 1


@requires_db
def test_large_value_stripe_payment_stays_integer_minor_units(
    client: TestClient, airports: list
) -> None:
    # EUR 100,000.00 operator amount + EUR 20,000.00 tax = EUR 120,000.00 total.
    scenario = booking_scenario(
        client, airports, operator_amount_minor=10_000_000, tax_amount_minor=2_000_000
    )
    with SessionLocal() as session:
        _onboarding_service(session).create_account(UUID(scenario["operator"]["id"]))

    with SessionLocal() as session:
        service = PaymentService(
            session,
            provider=StripeConnectPaymentProvider(FakeStripeGateway()),
            settings=stripe_test_settings(),
        )
        payment = service.create_for_booking(UUID(scenario["booking"]["id"]))
        payment_id = payment.id
        total = payment.total_amount_minor
        # Total is operator + platform fee + tax, all integer minor units, and at
        # this magnitude (> EUR 100k) must remain an exact integer with no float.
        assert total == payment.operator_amount_minor + payment.platform_fee_minor + (
            payment.tax_amount_minor
        )
        assert total >= 12_000_000
        assert isinstance(total, int)

        service.authorize(
            payment_id,
            PaymentAuthorize(idempotency_key=f"idem-{uuid4()}", payment_method_reference="pm_x"),
        )
        service.capture(payment_id, PaymentCapture(idempotency_key=f"idem-{uuid4()}"))

    with SessionLocal() as session:
        row = session.get(Payment, payment_id)
        assert row is not None
        assert row.status is PaymentStatus.CAPTURED
        assert row.captured_amount_minor == total
        assert isinstance(row.captured_amount_minor, int)
