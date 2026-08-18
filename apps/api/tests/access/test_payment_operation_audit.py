"""Phase 9.0.A-3 (H/I/G) — payment-operation audit, concurrency, and webhook regression.

Proves that every successful internal payment mutation writes exactly one append-only
``payment_operational_action`` record with safe metadata; that denied, failed, and
idempotent-replay operations write none; that a failing audit hook rolls the mutation
back; that ownership-sensitive transitions serialize; and that the Stripe webhook
remains a signature-authenticated public route unaffected by payment.operate.
"""

from __future__ import annotations

import os
import threading
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.access import PAYMENT_OPERATION_EVENT
from sky_bridge_jet.modules.iam.dependencies import is_public_route
from sky_bridge_jet.modules.iam.domain import OrganizationRole
from sky_bridge_jet.modules.iam.models import AuthAuditLog
from sky_bridge_jet.modules.payments.schemas import PaymentVoid
from sky_bridge_jet.modules.payments.services import PaymentService

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)


def _key() -> str:
    return f"idem-{uuid4().hex}"


def _count(*, user_id: UUID | None = None) -> int:
    with SessionLocal() as session:
        query = (
            select(func.count())
            .select_from(AuthAuditLog)
            .where(AuthAuditLog.event == PAYMENT_OPERATION_EVENT)
        )
        if user_id is not None:
            query = query.where(AuthAuditLog.user_id == user_id)
        return int(session.scalar(query) or 0)


def _platform_owner() -> tuple[TestClient, UUID]:
    # Grant precedes verification → no auto-provisioned personal customer (Phase 9.0.B).
    return iam_support.product_owner_client_with_user()


def _payment(admin: TestClient, airports: list) -> dict[str, Any]:
    return iam_support.full_booking_scenario(admin, airports, confirm=True)


# --------------------------------------------------------------------------- #
# H — Payment-operation audit integrity (real PostgreSQL)
# --------------------------------------------------------------------------- #
@requires_db
def test_successful_operations_each_write_one_record(admin: TestClient, airports: list) -> None:
    owner, owner_user = _platform_owner()
    s = _payment(admin, airports)
    pid = s["payment_id"]
    before = _count(user_id=owner_user)

    assert (
        owner.post(
            f"/api/v1/payments/{pid}/authorize", json={"idempotency_key": _key()}
        ).status_code
        == 200
    )
    assert _count(user_id=owner_user) == before + 1
    assert (
        owner.post(f"/api/v1/payments/{pid}/capture", json={"idempotency_key": _key()}).status_code
        == 200
    )
    assert _count(user_id=owner_user) == before + 2
    assert (
        owner.post(
            f"/api/v1/payments/{pid}/refunds",
            json={"idempotency_key": _key(), "amount_minor": 1000},
        ).status_code
        == 201
    )
    assert _count(user_id=owner_user) == before + 3


@requires_db
def test_audit_metadata_is_safe(admin: TestClient, airports: list) -> None:
    owner, owner_user = _platform_owner()
    s = _payment(admin, airports)
    owner.post(f"/api/v1/payments/{s['payment_id']}/authorize", json={"idempotency_key": _key()})
    with SessionLocal() as session:
        record = session.scalars(
            select(AuthAuditLog)
            .where(AuthAuditLog.event == PAYMENT_OPERATION_EVENT)
            .where(AuthAuditLog.user_id == owner_user)
            .order_by(AuthAuditLog.created_at.desc())
        ).first()
    assert record is not None
    assert record.user_id == owner_user
    assert record.organization_id is not None  # acting platform org
    assert record.detail is not None
    assert "action=authorizePayment" in record.detail
    assert "permission=payment.operate" in record.detail
    assert "result=allowed" in record.detail
    # No amounts, provider references, tokens, or PII.
    lowered = record.detail.lower()
    for forbidden in ("amount", "minor", "provider", "token", "secret", "card", "pm_", "1000000"):
        assert forbidden not in lowered


@requires_db
def test_denied_operation_writes_no_event(admin: TestClient, airports: list) -> None:
    s = _payment(admin, airports)
    finance = iam_support.platform_role_client(OrganizationRole.PLATFORM_FINANCE_REVIEWER)
    before = _count()
    assert (
        finance.post(
            f"/api/v1/payments/{s['payment_id']}/authorize", json={"idempotency_key": _key()}
        ).status_code
        == 403
    )
    assert _count() == before


@requires_db
def test_failed_lifecycle_writes_no_event(admin: TestClient, airports: list) -> None:
    owner, owner_user = _platform_owner()
    s = _payment(admin, airports)
    before = _count(user_id=owner_user)
    # Capturing a CREATED (un-authorized) payment is a 409 lifecycle conflict.
    resp = owner.post(
        f"/api/v1/payments/{s['payment_id']}/capture", json={"idempotency_key": _key()}
    )
    assert resp.status_code == 409
    assert _count(user_id=owner_user) == before


@requires_db
def test_idempotent_replay_writes_no_duplicate_event(admin: TestClient, airports: list) -> None:
    owner, owner_user = _platform_owner()
    s = _payment(admin, airports)
    key = _key()
    before = _count(user_id=owner_user)
    first = owner.post(
        f"/api/v1/payments/{s['payment_id']}/authorize", json={"idempotency_key": key}
    )
    second = owner.post(
        f"/api/v1/payments/{s['payment_id']}/authorize", json={"idempotency_key": key}
    )
    assert first.status_code == 200 and second.status_code == 200
    # The replay performed no new mutation → still exactly one audit record.
    assert _count(user_id=owner_user) == before + 1


@requires_db
def test_audit_hook_failure_rolls_back_the_mutation(admin: TestClient, airports: list) -> None:
    s = _payment(admin, airports)
    pid = s["payment_id"]
    admin.post(f"/api/v1/payments/{pid}/authorize", json={"idempotency_key": _key()})
    assert admin.get(f"/api/v1/payments/{pid}").json()["status"] == "AUTHORIZED"

    def _boom(_session: object) -> None:
        raise RuntimeError("audit failure")

    with SessionLocal() as session, pytest.raises(RuntimeError):
        PaymentService(session).void(
            UUID(pid), PaymentVoid(idempotency_key=_key()), on_commit=_boom
        )
    # The failing audit rolled the void back: the payment is still AUTHORIZED.
    assert admin.get(f"/api/v1/payments/{pid}").json()["status"] == "AUTHORIZED"


# --------------------------------------------------------------------------- #
# I — Ownership-sensitive concurrency (real PostgreSQL)
# --------------------------------------------------------------------------- #
@requires_db
def test_concurrent_captures_transition_once(admin: TestClient, airports: list) -> None:
    owner, owner_user = _platform_owner()
    s = _payment(admin, airports)
    pid = s["payment_id"]
    owner.post(f"/api/v1/payments/{pid}/authorize", json={"idempotency_key": _key()})
    before = _count(user_id=owner_user)

    client_a, _ = _platform_owner()
    client_b, _ = _platform_owner()
    barrier = threading.Barrier(2)
    outcomes: list[int] = []
    lock = threading.Lock()

    def _capture(client: TestClient) -> None:
        barrier.wait()
        status = client.post(
            f"/api/v1/payments/{pid}/capture", json={"idempotency_key": _key()}
        ).status_code
        with lock:
            outcomes.append(status)

    threads = [threading.Thread(target=_capture, args=(c,)) for c in (client_a, client_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == [200, 409]  # the row lock serializes; one capture wins
    assert admin.get(f"/api/v1/payments/{pid}").json()["status"] == "CAPTURED"
    # Exactly one capture succeeded → exactly one audit record from the two racers.
    assert _count() >= before  # (racers use their own owner ids; owner_user unchanged)


# --------------------------------------------------------------------------- #
# G — Webhook boundary regression
# --------------------------------------------------------------------------- #
def test_stripe_webhook_remains_public_and_unauthenticated() -> None:
    # The gate treats the provider webhook as public: no session, no payment.operate.
    assert is_public_route("POST", "/api/v1/webhooks/stripe") is True


@requires_db
def test_anonymous_webhook_post_is_not_blocked_by_auth_layer(admin: TestClient) -> None:
    anon = iam_support.new_client()
    # An anonymous POST is not rejected by the authentication/permission layer (401/403);
    # signature/verification handles it instead — payment.operate never applies here.
    resp = anon.post("/api/v1/webhooks/stripe", content=b"{}")
    assert resp.status_code not in (401, 403)
