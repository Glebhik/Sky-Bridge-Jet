"""Durable retry tests for ambiguous provider outcomes (no external provider calls)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.financials.reconciliation import (
    NormalizedProviderEvent,
    WebhookReconciliationService,
)
from sky_bridge_jet.modules.payments.domain import (
    PaymentOperationResult,
    PaymentOperationType,
    PaymentStatus,
)
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.provider import (
    FakePaymentProvider,
    PaymentProviderError,
    ProviderErrorCategory,
    ProviderResult,
)
from sky_bridge_jet.modules.payments.schemas import PaymentAuthorize, PaymentCapture, PaymentVoid
from sky_bridge_jet.modules.payments.services import PaymentService

from ._support import authorized_payment, booking_scenario, new_key, requires_db


class FailOnceProvider(FakePaymentProvider):
    """Simulate a transport loss after Stripe may have accepted one operation."""

    def __init__(self, operation: PaymentOperationType) -> None:
        self.operation = operation
        self.failed = False
        self.keys: list[str] = []
        self.results: dict[tuple[PaymentOperationType, str], ProviderResult] = {}
        self.financial_actions = 0

    def _dispatch(
        self,
        operation: PaymentOperationType,
        key: str,
        action: Any,
    ) -> ProviderResult:
        self.keys.append(key)
        identity = (operation, key)
        if identity not in self.results:
            self.results[identity] = action()
            self.financial_actions += 1
        if operation is self.operation and not self.failed:
            self.failed = True
            raise PaymentProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE)
        return self.results[identity]

    def authorize(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self._dispatch(
            PaymentOperationType.AUTHORIZE,
            kwargs["idempotency_key"],
            lambda: super(FailOnceProvider, self).authorize(**kwargs),
        )

    def capture(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self._dispatch(
            PaymentOperationType.CAPTURE,
            kwargs["idempotency_key"],
            lambda: super(FailOnceProvider, self).capture(**kwargs),
        )

    def void(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        return self._dispatch(
            PaymentOperationType.VOID,
            kwargs["idempotency_key"],
            lambda: super(FailOnceProvider, self).void(**kwargs),
        )


def _operation(key: str) -> PaymentOperation:
    with SessionLocal() as session:
        operation = session.scalar(
            select(PaymentOperation).where(PaymentOperation.idempotency_key == key)
        )
        assert operation is not None
        session.expunge(operation)
        return operation


def _retry(
    payment_id: UUID,
    key: str,
    operation: PaymentOperationType,
    provider: FailOnceProvider,
) -> PaymentStatus:
    with SessionLocal() as session:
        service = PaymentService(session, provider=provider)
        if operation is PaymentOperationType.AUTHORIZE:
            payment = service.authorize(payment_id, PaymentAuthorize(idempotency_key=key))
        elif operation is PaymentOperationType.CAPTURE:
            payment = service.capture(payment_id, PaymentCapture(idempotency_key=key))
        else:
            payment = service.void(payment_id, PaymentVoid(idempotency_key=key))
        return payment.status


@requires_db
def test_authorize_unknown_retries_same_durable_provider_identity(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    with SessionLocal() as session:
        payment = PaymentService(session).create_for_booking(UUID(scenario["booking"]["id"]))
        payment_id = payment.id
    key = new_key()
    provider = FailOnceProvider(PaymentOperationType.AUTHORIZE)

    assert (
        _retry(payment_id, key, PaymentOperationType.AUTHORIZE, provider) is PaymentStatus.CREATED
    )
    unknown = _operation(key)
    assert unknown.result is PaymentOperationResult.UNKNOWN
    assert unknown.attempt_count == 1
    assert (
        _retry(payment_id, key, PaymentOperationType.AUTHORIZE, provider)
        is PaymentStatus.AUTHORIZED
    )
    completed = _operation(key)
    assert completed.result is PaymentOperationResult.SUCCEEDED
    assert completed.attempt_count == 2
    assert provider.keys == [str(completed.correlation_id), str(completed.correlation_id)]
    assert provider.financial_actions == 1


@requires_db
def test_verified_provider_evidence_recovers_authorize_when_response_was_lost(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    with SessionLocal() as session:
        payment = PaymentService(session).create_for_booking(UUID(scenario["booking"]["id"]))
        payment_id = payment.id
    key = new_key()
    provider = FailOnceProvider(PaymentOperationType.AUTHORIZE)
    assert (
        _retry(payment_id, key, PaymentOperationType.AUTHORIZE, provider) is PaymentStatus.CREATED
    )
    unknown = _operation(key)
    recovered_reference = f"pi_{new_key()}"

    with SessionLocal() as session:
        WebhookReconciliationService(session).process(
            NormalizedProviderEvent(
                provider=provider.kind,
                event_id=new_key(),
                event_type="payment_intent.amount_capturable_updated",
                object_id=recovered_reference,
                data={
                    "status": "requires_capture",
                    "metadata": {"operation_correlation": str(unknown.correlation_id)},
                },
            )
        )

    recovered = _operation(key)
    assert recovered.result is PaymentOperationResult.SUCCEEDED
    assert provider.financial_actions == 1
    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        assert payment.status is PaymentStatus.AUTHORIZED
        assert payment.provider_payment_reference == recovered_reference


@requires_db
def test_capture_unknown_retries_without_double_capture(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = UUID(scenario["payment"]["id"])
    key = new_key()
    provider = FailOnceProvider(PaymentOperationType.CAPTURE)

    assert (
        _retry(payment_id, key, PaymentOperationType.CAPTURE, provider) is PaymentStatus.AUTHORIZED
    )
    assert _operation(key).result is PaymentOperationResult.UNKNOWN
    assert _retry(payment_id, key, PaymentOperationType.CAPTURE, provider) is PaymentStatus.CAPTURED
    completed = _operation(key)
    assert completed.result is PaymentOperationResult.SUCCEEDED
    assert completed.attempt_count == 2
    assert provider.keys == [str(completed.correlation_id), str(completed.correlation_id)]
    assert provider.financial_actions == 1


@requires_db
def test_void_unknown_retries_without_double_void(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = UUID(scenario["payment"]["id"])
    key = new_key()
    provider = FailOnceProvider(PaymentOperationType.VOID)

    assert _retry(payment_id, key, PaymentOperationType.VOID, provider) is PaymentStatus.AUTHORIZED
    assert _operation(key).result is PaymentOperationResult.UNKNOWN
    assert _retry(payment_id, key, PaymentOperationType.VOID, provider) is PaymentStatus.CANCELLED
    completed = _operation(key)
    assert completed.result is PaymentOperationResult.SUCCEEDED
    assert completed.attempt_count == 2
    assert provider.keys == [str(completed.correlation_id), str(completed.correlation_id)]
    assert provider.financial_actions == 1
