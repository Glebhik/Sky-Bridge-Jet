from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.domain import (
    ACTIVE_BOOKING_STATUSES,
    BookingConflictError,
    BookingStatus,
    generate_booking_reference,
)
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.schemas import (
    BookingCancel,
    BookingConfirm,
    BookingCreate,
    BookingReject,
)
from sky_bridge_jet.modules.bookings.services import BookingService

from ._support import booking_scenario, create_booking, requires_db

pytestmark = requires_db


def _raw_booking(scenario: dict[str, Any], **overrides: Any) -> Booking:
    offer = scenario["offer"]
    valid_until = offer["valid_until"]
    defaults: dict[str, Any] = {
        "reference": generate_booking_reference(),
        "trip_request_id": UUID(scenario["trip"]["id"]),
        "operator_offer_id": UUID(offer["id"]),
        "operator_id": UUID(offer["operator_id"]),
        "aircraft_id": UUID(offer["aircraft_id"]),
        "status": BookingStatus.PENDING_OPERATOR_CONFIRMATION,
        "currency": offer["currency"],
        "operator_amount_minor": offer["operator_amount_minor"],
        "platform_fee_minor": offer["platform_fee_minor"],
        "tax_amount_minor": offer["tax_amount_minor"],
        "total_amount_minor": offer["total_amount_minor"],
        "offer_valid_until": datetime.fromisoformat(valid_until) if valid_until else None,
        "operator_legal_name": offer["operator_legal_name"],
        "aircraft_registration": offer["aircraft_registration"],
        "aircraft_manufacturer": offer["aircraft_manufacturer"],
        "aircraft_model": offer["aircraft_model"],
        "aircraft_category": offer["aircraft_category"],
    }
    defaults.update(overrides)
    return Booking(**defaults)


def _active_count(trip_request_id: UUID) -> int:
    with SessionLocal() as session:
        return session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(
                Booking.trip_request_id == trip_request_id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            )
        )


# -- Database-level invariants, bypassing the service layer ------------------


def test_db_rejects_price_inconsistency(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_booking(scenario, total_amount_minor=1))
        session.commit()


def test_db_rejects_negative_amount(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario = booking_scenario(client, airports)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            _raw_booking(
                scenario,
                operator_amount_minor=-1,
                platform_fee_minor=0,
                tax_amount_minor=0,
                total_amount_minor=-1,
            )
        )
        session.commit()


def test_db_rejects_offer_operator_mismatch(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    other = booking_scenario(client, airports)
    # operator_id from a different scenario does not match the referenced offer.
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_booking(scenario, operator_id=UUID(other["offer"]["operator_id"])))
        session.commit()


def test_db_rejects_duplicate_reference(client: TestClient, airports: list[dict[str, Any]]) -> None:
    scenario_a = booking_scenario(client, airports)
    scenario_b = booking_scenario(client, airports)
    shared = generate_booking_reference()
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_booking(scenario_a, reference=shared))
        session.add(_raw_booking(scenario_b, reference=shared))
        session.commit()


def test_db_rejects_second_active_booking_for_trip(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(_raw_booking(scenario))
        session.add(_raw_booking(scenario))
        session.commit()


# -- Concurrency -------------------------------------------------------------


def test_concurrent_creation_yields_one_booking(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    payload = BookingCreate(
        trip_request_id=UUID(scenario["trip"]["id"]),
        operator_offer_id=UUID(scenario["offer"]["id"]),
    )
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).create(payload)
            result = "created"
        except (BookingConflictError, IntegrityError):
            result = "rejected"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["created", "rejected"]
    assert _active_count(UUID(scenario["trip"]["id"])) == 1


def test_confirm_reject_race_resolves_to_single_terminal_state(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking_id = UUID(create_booking(client, scenario).json()["id"])
    operator_id = UUID(scenario["operator"]["id"])
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def confirm() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).confirm(booking_id, BookingConfirm(operator_id=operator_id))
            outcome = "confirmed"
        except BookingConflictError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    def reject() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).reject(
                    booking_id, BookingReject(operator_id=operator_id, reason="OTHER")
                )
            outcome = "rejected"
        except BookingConflictError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=confirm), threading.Thread(target=reject)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert "conflict" in results  # exactly one command won
    with SessionLocal() as session:
        final = session.get(Booking, booking_id)
        assert final is not None
        assert final.status in {BookingStatus.CONFIRMED, BookingStatus.REJECTED}


def test_confirm_cancel_race_leaves_valid_state(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports)
    booking_id = UUID(create_booking(client, scenario).json()["id"])
    operator_id = UUID(scenario["operator"]["id"])
    barrier = threading.Barrier(2)

    def confirm() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).confirm(booking_id, BookingConfirm(operator_id=operator_id))
        except BookingConflictError:
            pass

    def cancel() -> None:
        barrier.wait()
        try:
            with SessionLocal() as session:
                BookingService(session).cancel(booking_id, BookingCancel(actor="PLATFORM"))
        except BookingConflictError:
            pass

    threads = [threading.Thread(target=confirm), threading.Thread(target=cancel)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Cancellation is legal from both PENDING and CONFIRMED, so the booking
    # deterministically ends cancelled without any contradictory state.
    with SessionLocal() as session:
        final = session.get(Booking, booking_id)
        assert final is not None
        assert final.status is BookingStatus.CANCELLED
