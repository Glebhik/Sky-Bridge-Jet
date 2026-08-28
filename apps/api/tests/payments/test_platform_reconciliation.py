"""Phase 9.8.B bounded finance discovery and same-identity reconciliation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import UUID

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from sky_bridge_jet.db.session import SessionLocal, engine
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.payments.domain import (
    InvalidPaymentStateError,
    PaymentOperationResult,
    PaymentOperationType,
)
from sky_bridge_jet.modules.payments.models import PaymentOperation
from sky_bridge_jet.modules.payments.schemas import PaymentAuthorize, PaymentCapture, PaymentVoid
from sky_bridge_jet.modules.payments.services import PaymentService

from ._support import authorized_payment, booking_scenario, new_key, requires_db
from .test_unknown_outcome import FailOnceProvider


def _unknown_authorize(client: TestClient, airports: list[dict[str, Any]]) -> PaymentOperation:
    scenario = booking_scenario(client, airports, confirm=False)
    with SessionLocal() as session:
        payment = PaymentService(session).create_for_booking(UUID(scenario["booking"]["id"]))
        payment_id = payment.id
    provider = FailOnceProvider(PaymentOperationType.AUTHORIZE)
    with SessionLocal() as session:
        PaymentService(session, provider=provider).authorize(
            payment_id, PaymentAuthorize(idempotency_key=new_key())
        )
    with SessionLocal() as session:
        row = session.scalar(
            select(PaymentOperation).where(
                PaymentOperation.payment_id == payment_id,
                PaymentOperation.result == PaymentOperationResult.UNKNOWN,
            )
        )
        assert row is not None
        session.expunge(row)
        return row


@requires_db
def test_queue_is_bounded_safe_and_read_only(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operation = _unknown_authorize(client, airports)
    with SessionLocal() as session:
        before = session.scalar(
            select(PaymentOperation.updated_at).where(PaymentOperation.id == operation.id)
        )
    response = client.get("/api/v1/platform/payments/exceptions?limit=1&offset=0")
    assert response.status_code == 200
    assert len(response.json()) == 1
    body = response.json()[0]
    assert body["can_reconcile"] is True
    forbidden = {"idempotency_key", "client_secret", "customer", "email", "card", "cvc"}
    assert forbidden.isdisjoint(body)
    with SessionLocal() as session:
        after = session.scalar(
            select(PaymentOperation.updated_at).where(PaymentOperation.id == operation.id)
        )
    assert before == after


@requires_db
def test_read_role_matrix_and_mutation_authority(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operation = _unknown_authorize(client, airports)
    finance = iam_support.platform_role_client(OrganizationRole.PLATFORM_FINANCE_REVIEWER)
    compliance = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    try:
        assert finance.get("/api/v1/platform/payments/exceptions").status_code == 200
        assert (
            finance.post(
                f"/api/v1/platform/payment-operations/{operation.id}/reconcile"
            ).status_code
            == 403
        )
        assert compliance.get("/api/v1/platform/payments/exceptions").status_code == 403
        assert (
            client.post(f"/api/v1/platform/payment-operations/{operation.id}/reconcile").status_code
            == 200
        )
    finally:
        finance.close()
        compliance.close()


@requires_db
def test_complete_platform_read_matrix_and_resource_oracle(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operation = _unknown_authorize(client, airports)
    detail_path = f"/api/v1/platform/payments/{operation.payment_id}"
    missing_path = "/api/v1/platform/payments/00000000-0000-4000-8000-000000000000"
    finance = iam_support.platform_role_client(OrganizationRole.PLATFORM_FINANCE_REVIEWER)
    support = iam_support.platform_role_client(OrganizationRole.PLATFORM_SUPPORT)
    compliance = iam_support.platform_role_client(OrganizationRole.PLATFORM_COMPLIANCE_REVIEWER)
    owner = iam_support.product_owner_client()
    anonymous = iam_support.new_client()
    try:
        for reader in (finance, support, client, owner):
            assert reader.get("/api/v1/platform/payments/exceptions").status_code == 200
            assert reader.get(detail_path).status_code == 200
        for denied in (compliance,):
            assert denied.get("/api/v1/platform/payments/exceptions").status_code == 403
            assert denied.get(detail_path).status_code == 403
            assert denied.get(missing_path).status_code == 403
        assert anonymous.get("/api/v1/platform/payments/exceptions").status_code == 401
        assert anonymous.get(detail_path).status_code == 401
        assert (
            owner.post(f"/api/v1/platform/payment-operations/{operation.id}/reconcile").status_code
            == 200
        )
        assert (
            support.post(
                f"/api/v1/platform/payment-operations/{operation.id}/reconcile"
            ).status_code
            == 403
        )
    finally:
        finance.close()
        support.close()
        compliance.close()
        owner.close()
        anonymous.close()


@pytest.mark.parametrize(
    "role",
    [
        OrganizationRole.CUSTOMER_OWNER,
        OrganizationRole.CUSTOMER_ASSISTANT,
        OrganizationRole.OPERATOR_ADMIN,
        OrganizationRole.OPERATOR_SALES,
        OrganizationRole.OPERATOR_OPERATIONS,
        OrganizationRole.OPERATOR_FINANCE,
        OrganizationRole.OPERATOR_COMPLIANCE,
    ],
)
@requires_db
def test_platform_payment_reads_deny_customer_and_operator_roles(
    client: TestClient, airports: list[dict[str, Any]], role: OrganizationRole
) -> None:
    operation = _unknown_authorize(client, airports)
    payment_id = operation.payment_id
    if role in {OrganizationRole.CUSTOMER_OWNER, OrganizationRole.CUSTOMER_ASSISTANT}:
        customer_id = iam_support.create_customer(client)
        owner, organization_id = iam_support.customer_owner_client(client, customer_id)
        if role is OrganizationRole.CUSTOMER_OWNER:
            caller = owner
        else:
            owner.close()
            caller = iam_support.member_client_for_org(organization_id, role)
    else:
        operator_id = iam_support.create_operator(client)
        caller, _ = iam_support.operator_role_client(operator_id, role)
    try:
        queue = caller.get("/api/v1/platform/payments/exceptions")
        detail = caller.get(f"/api/v1/platform/payments/{payment_id}")
        assert queue.status_code == 403
        assert detail.status_code == 403
        assert str(payment_id) not in queue.text
        assert str(payment_id) not in detail.text
    finally:
        caller.close()


@requires_db
def test_reconcile_reuses_operation_and_rejects_second_attempt(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operation = _unknown_authorize(client, airports)
    first = client.post(f"/api/v1/platform/payment-operations/{operation.id}/reconcile")
    assert first.status_code == 200
    second = client.post(f"/api/v1/platform/payment-operations/{operation.id}/reconcile")
    assert second.status_code == 409
    with SessionLocal() as session:
        rows = session.scalars(
            select(PaymentOperation).where(PaymentOperation.id == operation.id)
        ).all()
        assert len(rows) == 1
        assert rows[0].correlation_id == operation.correlation_id
        assert rows[0].idempotency_key == operation.idempotency_key
        assert rows[0].attempt_count == 2


@pytest.mark.parametrize(
    ("result", "operation_type"),
    [
        (PaymentOperationResult.PENDING, PaymentOperationType.AUTHORIZE),
        (PaymentOperationResult.FAILED, PaymentOperationType.AUTHORIZE),
        (PaymentOperationResult.UNKNOWN, PaymentOperationType.REFUND),
    ],
)
@requires_db
def test_pending_failed_and_refund_reconciliation_fail_closed(
    client: TestClient,
    airports: list[dict[str, Any]],
    result: PaymentOperationResult,
    operation_type: PaymentOperationType,
) -> None:
    operation = _unknown_authorize(client, airports)
    with SessionLocal() as session, session.begin():
        row = session.get(PaymentOperation, operation.id)
        assert row is not None
        row.result = result
        row.operation = operation_type
        before_attempts = row.attempt_count
    response = client.post(f"/api/v1/platform/payment-operations/{operation.id}/reconcile")
    assert response.status_code == 409
    with SessionLocal() as session:
        row = session.get(PaymentOperation, operation.id)
        assert row is not None
        assert row.result is result
        assert row.operation is operation_type
        assert row.attempt_count == before_attempts


@requires_db
def test_second_lost_response_remains_unknown_with_same_identity(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    with SessionLocal() as session:
        payment = PaymentService(session).create_for_booking(UUID(scenario["booking"]["id"]))
        payment_id = payment.id
    key = new_key()
    provider = FailOnceProvider(PaymentOperationType.AUTHORIZE)
    with SessionLocal() as session:
        PaymentService(session, provider=provider).authorize(
            payment_id, PaymentAuthorize(idempotency_key=key)
        )
    with SessionLocal() as session:
        original = session.scalar(
            select(PaymentOperation).where(PaymentOperation.idempotency_key == key)
        )
        assert original is not None
        operation_id = original.id
        correlation_id = original.correlation_id
    provider.failed = False
    with SessionLocal() as session:
        PaymentService(session, provider=provider).reconcile_operation(operation_id)
    with SessionLocal() as session:
        row = session.get(PaymentOperation, operation_id)
        assert row is not None
        assert row.result is PaymentOperationResult.UNKNOWN
        assert row.idempotency_key == key
        assert row.correlation_id == correlation_id
        assert row.attempt_count == 2
        assert provider.financial_actions == 1


class _BlockingAuthorizeProvider(FailOnceProvider):
    def __init__(self) -> None:
        super().__init__(PaymentOperationType.AUTHORIZE)
        self.failed = True
        self.entered = Event()
        self.release = Event()
        self.dispatches = 0

    def authorize(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.dispatches += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().authorize(**kwargs)


@requires_db
def test_concurrent_reconciliation_dispatches_once(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operation = _unknown_authorize(client, airports)
    provider = _BlockingAuthorizeProvider()

    def reconcile() -> str:
        try:
            with SessionLocal() as session:
                PaymentService(session, provider=provider).reconcile_operation(operation.id)
            return "succeeded"
        except InvalidPaymentStateError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(reconcile)
        assert provider.entered.wait(timeout=5)
        second = pool.submit(reconcile)
        assert second.result(timeout=5) == "conflict"
        provider.release.set()
        assert first.result(timeout=5) == "succeeded"
    assert provider.dispatches == 1


@requires_db
def test_lost_capture_and_void_reuse_same_provider_identity(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    for operation_type in (PaymentOperationType.CAPTURE, PaymentOperationType.VOID):
        scenario = authorized_payment(client, airports)
        payment_id = UUID(scenario["payment"]["id"])
        key = new_key()
        provider = FailOnceProvider(operation_type)
        with SessionLocal() as session:
            service = PaymentService(session, provider=provider)
            if operation_type is PaymentOperationType.CAPTURE:
                service.capture(payment_id, PaymentCapture(idempotency_key=key))
            else:
                service.void(payment_id, PaymentVoid(idempotency_key=key))
        with SessionLocal() as session:
            row = session.scalar(
                select(PaymentOperation).where(PaymentOperation.idempotency_key == key)
            )
            assert row is not None and row.result is PaymentOperationResult.UNKNOWN
            operation_id = row.id
            correlation_id = row.correlation_id
        response = client.post(f"/api/v1/platform/payment-operations/{operation_id}/reconcile")
        assert response.status_code == 200
        with SessionLocal() as session:
            row = session.get(PaymentOperation, operation_id)
            assert row is not None
            assert row.result is PaymentOperationResult.SUCCEEDED
            assert row.correlation_id == correlation_id
            assert row.idempotency_key == key
            assert row.attempt_count == 2


@requires_db
def test_large_queue_is_one_query(client: TestClient, airports: list[dict[str, Any]]) -> None:
    _unknown_authorize(client, airports)
    count = 0

    def before_cursor(*_: object) -> None:
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", before_cursor)
    try:
        with SessionLocal() as session:
            rows = PaymentService(session).list_platform_exceptions(
                results=[
                    PaymentOperationResult.PENDING,
                    PaymentOperationResult.UNKNOWN,
                    PaymentOperationResult.FAILED,
                ],
                operation=None,
                limit=100,
                offset=0,
            )
            assert rows
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor)
    assert count == 1


def test_openapi_contract_is_closed() -> None:
    schema = iam_support.new_client().get("/openapi.json").json()
    path = schema["paths"]["/api/v1/platform/payment-operations/{operation_id}/reconcile"]["post"]
    assert "requestBody" not in path
    detail = schema["components"]["schemas"]["PlatformPaymentDetailResponse"]["properties"]
    assert "client_secret" not in detail
    assert "idempotency_key" not in detail
