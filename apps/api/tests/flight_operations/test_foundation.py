from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from payments._support import booking_scenario
from sqlalchemy import delete, event, func, select

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.flight_operations.domain import FlightOperationEligibilityError
from sky_bridge_jet.modules.flight_operations.models import FlightOperation
from sky_bridge_jet.modules.flight_operations.services import FlightOperationService
from sky_bridge_jet.modules.iam.domain import OrganizationRole, OrganizationType
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership
from sky_bridge_jet.modules.iam.router import _register_limiter
from sky_bridge_jet.modules.notifications.domain import MarketplaceNotificationEvent
from sky_bridge_jet.modules.notifications.models import NotificationOutbox
from sky_bridge_jet.modules.payments.models import Payment

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

_ROLES = (
    OrganizationRole.OPERATOR_ADMIN,
    OrganizationRole.OPERATOR_SALES,
    OrganizationRole.OPERATOR_OPERATIONS,
    OrganizationRole.OPERATOR_FINANCE,
    OrganizationRole.OPERATOR_COMPLIANCE,
)
_SAFE_FIELDS = {
    "operation_id",
    "booking_id",
    "booking_reference",
    "status",
    "booking_status",
    "aircraft_registration",
    "aircraft_manufacturer",
    "aircraft_model",
    "aircraft_category",
    "legs",
    "created_at",
    "updated_at",
}
_FORBIDDEN = {
    "customer_id",
    "customer_name",
    "customer_email",
    "operator_id",
    "passengers",
    "passport",
    "nationality",
    "date_of_birth",
    "requirements",
    "confirmation_note",
    "platform_fee_minor",
    "tax_amount_minor",
    "total_amount_minor",
    "payment",
    "provider_reference",
    "client_secret",
}


def _operator_actor(operator_id: str, role: OrganizationRole) -> TestClient:
    _register_limiter.clear()
    with SessionLocal() as session:
        organization_id = session.scalar(
            select(Organization.id).where(Organization.operator_id == UUID(operator_id))
        )
    if organization_id is None:
        actor, organization_id = iam_support.operator_role_client(UUID(operator_id), role)
    else:
        actor = iam_support.member_client_for_org(organization_id, role)
    actor.headers["X-Organization-Id"] = str(organization_id)
    return actor


def _confirm(client: TestClient, scenario: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/bookings/{scenario['booking']['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_confirmation_creates_one_atomic_operation_and_preserves_other_domains(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    booking_id = UUID(scenario["booking"]["id"])
    customer_actor, _ = iam_support.customer_owner_client(client, UUID(scenario["customer"]["id"]))
    customer_actor.close()
    confirmed = _confirm(client, scenario)
    assert confirmed["status"] == "CONFIRMED"

    with SessionLocal() as session:
        operations = list(
            session.scalars(select(FlightOperation).where(FlightOperation.booking_id == booking_id))
        )
        assert len(operations) == 1
        assert operations[0].status.value == "HANDOFF_CREATED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(
                    NotificationOutbox.resource_id == booking_id,
                    NotificationOutbox.event_type
                    == MarketplaceNotificationEvent.BOOKING_CONFIRMED.value,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Payment).where(Payment.booking_id == booking_id)
            )
            == 0
        )
    assert (
        client.post(f"/api/v1/bookings/{booking_id}/cancel", json={"actor": "CUSTOMER"}).status_code
        == 200
    )
    with SessionLocal() as session:
        retained = session.scalar(
            select(FlightOperation).where(FlightOperation.booking_id == booking_id)
        )
        assert retained is not None
        assert session.get_one(Booking, booking_id).status is BookingStatus.CANCELLED


def test_non_confirmed_rejected_and_cancelled_bookings_do_not_create_operations(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    pending = booking_scenario(client, airports, confirm=False)
    pending_id = UUID(pending["booking"]["id"])
    with SessionLocal.begin() as session:
        with pytest.raises(FlightOperationEligibilityError):
            FlightOperationService(session).ensure_for_confirmed_booking(pending_id)

    rejected = booking_scenario(client, airports, confirm=False)
    assert (
        client.post(
            f"/api/v1/bookings/{rejected['booking']['id']}/reject",
            json={"operator_id": rejected["operator"]["id"], "reason": "OTHER"},
        ).status_code
        == 200
    )
    cancelled = booking_scenario(client, airports, confirm=False)
    assert (
        client.post(
            f"/api/v1/bookings/{cancelled['booking']['id']}/cancel",
            json={"actor": "CUSTOMER"},
        ).status_code
        == 200
    )
    with SessionLocal() as session:
        ids = {
            pending_id,
            UUID(rejected["booking"]["id"]),
            UUID(cancelled["booking"]["id"]),
        }
        assert (
            session.scalar(
                select(func.count())
                .select_from(FlightOperation)
                .where(FlightOperation.booking_id.in_(ids))
            )
            == 0
        )


def test_creation_is_idempotent_concurrent_and_restart_durable(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    booking_id = UUID(scenario["booking"]["id"])
    _confirm(client, scenario)
    with SessionLocal.begin() as session:
        session.execute(delete(FlightOperation).where(FlightOperation.booking_id == booking_id))

    def ensure() -> UUID:
        with SessionLocal.begin() as session:
            return FlightOperationService(session).ensure_for_confirmed_booking(booking_id).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: ensure(), range(2)))
    assert len(set(ids)) == 1
    with SessionLocal() as fresh_session:
        persisted = FlightOperationService(fresh_session).operations.get_by_booking(booking_id)
        assert persisted is not None
        assert persisted.id == ids[0]


def test_operation_failure_rolls_back_confirmation_and_notification(
    client: TestClient, airports: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    booking_id = UUID(scenario["booking"]["id"])
    original = FlightOperationService.ensure_for_confirmed_booking

    def fail_after_insert(self: FlightOperationService, target: UUID) -> FlightOperation:
        original(self, target)
        raise RuntimeError("forced D0 rollback")

    monkeypatch.setattr(FlightOperationService, "ensure_for_confirmed_booking", fail_after_insert)
    with pytest.raises(RuntimeError, match="forced D0 rollback"):
        client.post(
            f"/api/v1/bookings/{booking_id}/confirm",
            json={"operator_id": scenario["operator"]["id"]},
        )
    with SessionLocal() as session:
        assert (
            session.get_one(Booking, booking_id).status
            is BookingStatus.PENDING_OPERATOR_CONFIRMATION
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FlightOperation)
                .where(FlightOperation.booking_id == booking_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(
                    NotificationOutbox.resource_id == booking_id,
                    NotificationOutbox.event_type
                    == MarketplaceNotificationEvent.BOOKING_CONFIRMED.value,
                )
            )
            == 0
        )


def test_operator_reads_are_role_scoped_private_bounded_and_constant_query(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = booking_scenario(client, airports, confirm=False)
    _confirm(client, scenario)
    actor = _operator_actor(scenario["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    first = actor.get("/api/v1/me/operator-operations?limit=1&offset=0")
    assert first.status_code == 200
    item = first.json()[0]
    assert set(item) == _SAFE_FIELDS
    assert _FORBIDDEN.isdisjoint(item)
    detail = actor.get(f"/api/v1/me/operator-operations/{item['operation_id']}")
    assert detail.status_code == 200
    assert detail.json() == item
    assert actor.get("/api/v1/me/operator-operations?limit=101").status_code == 422
    actor.close()

    for role in _ROLES:
        role_actor = _operator_actor(scenario["operator"]["id"], role)
        assert role_actor.get("/api/v1/me/operator-operations").status_code == 200
        role_actor.close()

    anonymous = iam_support.new_client()
    assert anonymous.get("/api/v1/me/operator-operations").status_code == 401
    anonymous.close()
    customer = iam_support.new_client()
    iam_support.register_verify_login(customer)
    assert customer.get("/api/v1/me/operator-operations").status_code == 403
    customer.close()

    foreign = booking_scenario(client, airports, confirm=False)
    _confirm(client, foreign)
    foreign_actor = _operator_actor(foreign["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    assert (
        foreign_actor.get(f"/api/v1/me/operator-operations/{item['operation_id']}").status_code
        == 404
    )
    foreign_actor.close()

    with SessionLocal() as session:
        operation = session.get_one(FlightOperation, UUID(item["operation_id"]))
        booking = session.get_one(Booking, operation.booking_id)
        for _ in range(105):
            clone = Booking(
                reference=f"D0-{uuid4().hex[:20].upper()}",
                trip_request_id=booking.trip_request_id,
                operator_offer_id=booking.operator_offer_id,
                operator_id=booking.operator_id,
                aircraft_id=booking.aircraft_id,
                status=BookingStatus.CANCELLED,
                currency=booking.currency,
                operator_amount_minor=booking.operator_amount_minor,
                platform_fee_minor=booking.platform_fee_minor,
                tax_amount_minor=booking.tax_amount_minor,
                total_amount_minor=booking.total_amount_minor,
                offer_valid_until=booking.offer_valid_until,
                operator_legal_name=booking.operator_legal_name,
                aircraft_registration=booking.aircraft_registration,
                aircraft_manufacturer=booking.aircraft_manufacturer,
                aircraft_model=booking.aircraft_model,
                aircraft_category=booking.aircraft_category,
                cancelled_at=booking.confirmed_at,
            )
            session.add(clone)
            session.flush()
            session.add(FlightOperation(booking_id=clone.id))
        session.commit()

    with SessionLocal() as session:
        before = {
            model: session.scalar(select(func.count()).select_from(model))
            for model in (Booking, FlightOperation, Payment, NotificationOutbox)
        }
    actor = _operator_actor(scenario["operator"]["id"], OrganizationRole.OPERATOR_ADMIN)
    assert len(actor.get("/api/v1/me/operator-operations?limit=100&offset=0").json()) == 100
    assert len(actor.get("/api/v1/me/operator-operations?limit=100&offset=100").json()) >= 6
    actor.close()
    with SessionLocal() as session:
        after = {
            model: session.scalar(select(func.count()).select_from(model))
            for model in (Booking, FlightOperation, Payment, NotificationOutbox)
        }
    assert after == before

    for limit in (1, 20, 100):
        statements = 0

        def count_statement(*_args: object) -> None:
            nonlocal statements
            statements += 1

        with SessionLocal() as session:
            connection = session.connection()
            event.listen(connection, "before_cursor_execute", count_statement)
            try:
                views = FlightOperationService(session).list_for_operator(
                    UUID(scenario["operator"]["id"]), limit=limit, offset=0
                )
            finally:
                event.remove(connection, "before_cursor_execute", count_statement)
        assert len(views) == limit
        assert statements == 2


def test_active_organization_is_the_only_tenant_authority(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenarios = [booking_scenario(client, airports, confirm=False) for _ in range(2)]
    for scenario in scenarios:
        _confirm(client, scenario)
    actor = iam_support.new_client()
    organizations: list[UUID] = []

    def grant(user_id: UUID) -> None:
        with SessionLocal.begin() as session:
            for scenario in scenarios:
                organization = Organization(
                    organization_type=OrganizationType.OPERATOR,
                    display_name="D0 multi-org operator",
                    operator_id=UUID(scenario["operator"]["id"]),
                )
                session.add(organization)
                session.flush()
                organizations.append(organization.id)
                session.add(
                    OrganizationMembership(
                        user_id=user_id,
                        organization_id=organization.id,
                        role=OrganizationRole.OPERATOR_OPERATIONS,
                    )
                )

    _register_limiter.clear()
    iam_support.register_verify_login(actor, before_verify=grant)
    assert actor.get("/api/v1/me/operator-operations").status_code == 403
    for index, organization_id in enumerate(organizations):
        actor.headers["X-Organization-Id"] = str(organization_id)
        rows = actor.get("/api/v1/me/operator-operations").json()
        expected_booking = scenarios[index]["booking"]["id"]
        assert [row["booking_id"] for row in rows] == [expected_booking]
    actor.headers["X-Organization-Id"] = str(uuid4())
    assert actor.get("/api/v1/me/operator-operations").status_code == 403
    actor.close()
