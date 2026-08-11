from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.payments.domain import (
    PaymentConflictError,
    PaymentStatus,
    generate_payment_reference,
)
from sky_bridge_jet.modules.payments.models import Payment
from sky_bridge_jet.modules.payments.schemas import (
    PaymentAuthorize,
    PaymentCapture,
    PaymentVoid,
    RefundCreate,
)
from sky_bridge_jet.modules.payments.services import PaymentService

from ._support import (
    authorized_payment,
    booking_scenario,
    capture,
    create_payment,
    new_key,
    requires_db,
)

pytestmark = requires_db


def _raw_payment(booking: dict[str, Any], **overrides: Any) -> Payment:
    defaults: dict[str, Any] = {
        "reference": generate_payment_reference(),
        "booking_id": UUID(booking["id"]),
        "status": PaymentStatus.CREATED,
        "currency": booking["currency"],
        "operator_amount_minor": booking["operator_amount_minor"],
        "platform_fee_minor": booking["platform_fee_minor"],
        "tax_amount_minor": booking["tax_amount_minor"],
        "total_amount_minor": booking["total_amount_minor"],
        "captured_amount_minor": 0,
        "refunded_amount_minor": 0,
    }
    defaults.update(overrides)
    return Payment(**defaults)


# -- Database-level invariants, bypassing the service layer ------------------


def test_db_rejects_price_inconsistency(client: TestClient, airports: list[dict[str, Any]]) -> None:
    booking = booking_scenario(client, airports)["booking"]
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_payment(booking, total_amount_minor=booking["total_amount_minor"] + 1))
        session.commit()


def test_db_rejects_snapshot_divergence_from_booking(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    booking = booking_scenario(client, airports)["booking"]
    # Internally consistent, but the split diverges from the booking → composite FK fails.
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            _raw_payment(
                booking,
                operator_amount_minor=booking["operator_amount_minor"] + 1000,
                total_amount_minor=booking["total_amount_minor"] + 1000,
            )
        )
        session.commit()


def test_db_rejects_captured_over_authorized(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    booking = booking_scenario(client, airports)["booking"]
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_payment(booking, authorized_amount_minor=100, captured_amount_minor=200))
        session.commit()


def test_db_rejects_refunded_over_captured(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    booking = booking_scenario(client, airports)["booking"]
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            _raw_payment(
                booking,
                authorized_amount_minor=1000,
                captured_amount_minor=100,
                refunded_amount_minor=200,
            )
        )
        session.commit()


def test_db_rejects_second_payment_for_booking(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    booking = booking_scenario(client, airports)["booking"]
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_payment(booking))
        session.add(_raw_payment(booking))
        session.commit()


# -- Concurrency -------------------------------------------------------------


def test_concurrent_payment_creation_yields_one(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    booking_id = UUID(booking_scenario(client, airports)["booking"]["id"])
    barrier = threading.Barrier(2)
    ids: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                payment = PaymentService(session).create_for_booking(booking_id)
                result = str(payment.id)
        except (PaymentConflictError, IntegrityError):
            result = "conflict"
        with lock:
            ids.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as session:
        count = len(session.query(Payment).filter(Payment.booking_id == booking_id).all())
    assert count == 1


def test_concurrent_capture_captures_once(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = UUID(scenario["payment"]["id"])
    total = scenario["payment"]["total_amount_minor"]
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).capture(
                    payment_id, PaymentCapture(idempotency_key=new_key())
                )
            result = "captured"
        except PaymentConflictError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["captured", "conflict"]
    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        assert payment.status is PaymentStatus.CAPTURED
        assert payment.captured_amount_minor == total  # captured exactly once


def test_capture_versus_void_race_single_winner(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = UUID(scenario["payment"]["id"])
    barrier = threading.Barrier(2)

    def do_capture() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).capture(
                    payment_id, PaymentCapture(idempotency_key=new_key())
                )
        except PaymentConflictError:
            pass

    def do_void() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).void(payment_id, PaymentVoid(idempotency_key=new_key()))
        except PaymentConflictError:
            pass

    threads = [threading.Thread(target=do_capture), threading.Thread(target=do_void)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        assert payment.status in {PaymentStatus.CAPTURED, PaymentStatus.CANCELLED}
        if payment.status is PaymentStatus.CANCELLED:
            assert payment.captured_amount_minor == 0


def test_concurrent_full_refund_no_over_refund(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = authorized_payment(client, airports)
    payment_id = scenario["payment"]["id"]
    capture(client, payment_id)
    total = scenario["payment"]["total_amount_minor"]
    puuid = UUID(payment_id)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).refund(
                    puuid, RefundCreate(idempotency_key=new_key(), amount_minor=total)
                )
            result = "refunded"
        except PaymentConflictError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["conflict", "refunded"]
    with SessionLocal() as session:
        payment = session.get(Payment, puuid)
        assert payment is not None
        assert payment.refunded_amount_minor == total  # never over-refunded
        assert payment.status is PaymentStatus.REFUNDED


def test_duplicate_authorize_same_key_authorizes_once(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    payment = create_payment(client, scenario["booking"]["id"])
    payment_id = UUID(payment["id"])
    key = new_key()
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    outcomes: list[str] = []

    def attempt() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                PaymentService(session).authorize(payment_id, PaymentAuthorize(idempotency_key=key))
            result = "ok"
        except (PaymentConflictError, IntegrityError):
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as session:
        payment_row = session.get(Payment, payment_id)
        assert payment_row is not None
        assert payment_row.status is PaymentStatus.AUTHORIZED
        authorize_ops = [op for op in payment_row.operations if op.idempotency_key == key]
        assert len(authorize_ops) == 1  # exactly one authorization recorded
