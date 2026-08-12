from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.bookings.schemas import BookingConfirm
from sky_bridge_jet.modules.bookings.services import BookingService
from sky_bridge_jet.modules.compliance.domain import (
    AircraftAuthorizationStatus,
    AuthorityBasis,
    ComplianceConflictError,
    EvidenceStatus,
    EvidenceType,
    OperatorAdmissionStatus,
)
from sky_bridge_jet.modules.compliance.models import (
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.compliance.schemas import AdmissionReviewCommand, EvidenceReviewCommand
from sky_bridge_jet.modules.compliance.services import ComplianceService
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.offers.schemas import OperatorOfferCreate
from sky_bridge_jet.modules.offers.services import OperatorOfferService

from ._support import (
    create_aircraft,
    create_operator,
    eligible_operator_aircraft,
    pending_booking,
    requires_db,
    submitted_trip,
)

pytestmark = requires_db

_SUSPEND = AdmissionReviewCommand(action="SUSPEND", actor_type="PLATFORM_REVIEWER")
_APPROVE = AdmissionReviewCommand(action="APPROVE", actor_type="PLATFORM_REVIEWER")


def _now() -> datetime:
    return datetime.now(UTC)


# -- Database-level invariants ----------------------------------------------


def test_db_rejects_invalid_validity_window(client: TestClient) -> None:
    operator = create_operator(client)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            ComplianceEvidence(
                operator_id=UUID(operator["id"]),
                evidence_type=EvidenceType.INSURANCE,
                status=EvidenceStatus.SUBMITTED,
                effective_date=_now() + timedelta(days=10),
                expiry_date=_now(),
            )
        )
        session.commit()


def test_db_rejects_evidence_aircraft_of_another_operator(client: TestClient) -> None:
    operator_a = create_operator(client)
    operator_b = create_operator(client)
    aircraft_b = create_aircraft(client, operator_b["id"])
    with SessionLocal() as session, pytest.raises(IntegrityError):
        session.add(
            ComplianceEvidence(
                operator_id=UUID(operator_a["id"]),
                aircraft_id=UUID(aircraft_b["id"]),
                evidence_type=EvidenceType.AIRCRAFT_OPERATING_AUTHORITY,
                status=EvidenceStatus.SUBMITTED,
            )
        )
        session.commit()


def test_db_rejects_duplicate_admission(client: TestClient) -> None:
    operator = create_operator(client)
    with SessionLocal() as session, pytest.raises(IntegrityError):
        for _ in range(2):
            session.add(
                OperatorAdmission(
                    operator_id=UUID(operator["id"]), status=OperatorAdmissionStatus.DRAFT
                )
            )
        session.commit()


def test_db_rejects_duplicate_authorization_pair(client: TestClient) -> None:
    operator = create_operator(client)
    aircraft = create_aircraft(client, operator["id"])
    with SessionLocal() as session, pytest.raises(IntegrityError):
        for _ in range(2):
            session.add(
                OperatorAircraftAuthorization(
                    operator_id=UUID(operator["id"]),
                    aircraft_id=UUID(aircraft["id"]),
                    status=AircraftAuthorizationStatus.DRAFT,
                    authority_basis=AuthorityBasis.OWNED,
                )
            )
        session.commit()


# -- Concurrency ------------------------------------------------------------


def _run(targets: list[Any]) -> None:
    barrier = threading.Barrier(len(targets))

    def wrapped(fn: Any) -> None:
        barrier.wait()
        fn()

    threads = [threading.Thread(target=wrapped, args=(fn,)) for fn in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_concurrent_admission_approval_single_winner(client: TestClient) -> None:
    operator = create_operator(client)
    oid = UUID(operator["id"])
    client.post(f"/api/v1/operators/{operator['id']}/admission")
    client.post(f"/api/v1/operators/{operator['id']}/admission/submit")
    outcomes: list[str] = []
    lock = threading.Lock()

    def approve() -> None:
        try:
            with SessionLocal() as session:
                ComplianceService(session).review_admission(oid, _APPROVE)
            result = "approved"
        except ComplianceConflictError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    _run([approve, approve])
    assert sorted(outcomes) == ["approved", "conflict"]
    with SessionLocal() as session:
        admission = session.scalar(
            select(OperatorAdmission).where(OperatorAdmission.operator_id == oid)
        )
        assert admission is not None
        assert admission.status is OperatorAdmissionStatus.APPROVED


def test_concurrent_evidence_verification_single_winner(client: TestClient) -> None:
    operator = create_operator(client)
    evidence = client.post(
        f"/api/v1/operators/{operator['id']}/evidence",
        json={"evidence_type": "INSURANCE", "insurer_name": "Acme"},
    ).json()
    eid = UUID(evidence["id"])
    verify = EvidenceReviewCommand(action="VERIFY", actor_type="PLATFORM_REVIEWER")
    outcomes: list[str] = []
    lock = threading.Lock()

    def do_verify() -> None:
        try:
            with SessionLocal() as session:
                ComplianceService(session).review_evidence(eid, verify)
            result = "verified"
        except ComplianceConflictError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    _run([do_verify, do_verify])
    assert sorted(outcomes) == ["conflict", "verified"]
    with SessionLocal() as session:
        assert session.get(ComplianceEvidence, eid).status is EvidenceStatus.VERIFIED


def test_concurrent_suspend_versus_offer_creation(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    operator, aircraft = eligible_operator_aircraft(client)
    oid = UUID(operator["id"])
    trip = submitted_trip(client, airports)
    offer_data = OperatorOfferCreate(
        trip_request_id=UUID(trip["id"]),
        operator_id=oid,
        aircraft_id=UUID(aircraft["id"]),
        currency="EUR",
        operator_amount_minor=1_000_000,
        tax_amount_minor=0,
        valid_until=_now() + timedelta(days=30),
    )
    result: dict[str, str] = {}
    lock = threading.Lock()

    def suspend() -> None:
        with SessionLocal() as session:
            ComplianceService(session).review_admission(oid, _SUSPEND)

    def create_offer() -> None:
        try:
            with SessionLocal() as session:
                OperatorOfferService(session).create(offer_data)
            outcome = "created"
        except ComplianceConflictError:
            outcome = "blocked"
        with lock:
            result["offer"] = outcome

    _run([suspend, create_offer])

    # The admission row lock serializes the two; the outcome is always consistent.
    assert result["offer"] in {"created", "blocked"}
    with SessionLocal() as session:
        offers = (
            session.query(OperatorOffer)
            .filter(OperatorOffer.trip_request_id == UUID(trip["id"]))
            .count()
        )
        if result["offer"] == "blocked":
            assert offers == 0  # never an offer from a suspended operator
        else:
            assert offers == 1


def test_concurrent_confirm_versus_suspend_never_confirms_under_suspension(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = pending_booking(client, airports)
    oid = UUID(scenario["operator"]["id"])
    booking_id = UUID(scenario["booking"]["id"])
    confirm_command = BookingConfirm(operator_id=oid)
    result: dict[str, str] = {}
    lock = threading.Lock()

    def suspend() -> None:
        with SessionLocal() as session:
            ComplianceService(session).review_admission(oid, _SUSPEND)

    def confirm() -> None:
        try:
            with SessionLocal() as session:
                BookingService(session).confirm(booking_id, confirm_command)
            outcome = "confirmed"
        except ComplianceConflictError:
            outcome = "blocked"
        with lock:
            result["confirm"] = outcome

    _run([suspend, confirm])

    with SessionLocal() as session:
        booking = session.get(Booking, booking_id)
        assert booking is not None
        if result["confirm"] == "blocked":
            assert booking.status is BookingStatus.PENDING_OPERATOR_CONFIRMATION
        else:
            # Confirmation only succeeds if it held the admission lock first (still
            # approved at that instant); a later suspension is permitted.
            assert booking.status is BookingStatus.CONFIRMED
