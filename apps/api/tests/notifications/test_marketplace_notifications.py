from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID, uuid4

import iam_support
import pytest
from fastapi.testclient import TestClient
from payments._support import make_operator_eligible
from sqlalchemy import delete, event, func, select

from sky_bridge_jet.core.config import Settings, get_settings
from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.bookings.domain import BookingStatus
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.core_aviation.seed import seed_airports
from sky_bridge_jet.modules.iam.domain import (
    MembershipStatus,
    OrganizationRole,
    OrganizationType,
    UserStatus,
)
from sky_bridge_jet.modules.iam.models import Organization, OrganizationMembership, User
from sky_bridge_jet.modules.notifications.delivery import (
    FakeDeliveryMode,
    FakeMarketplaceNotificationSender,
    MarketplaceEmail,
    NotificationDeliveryError,
)
from sky_bridge_jet.modules.notifications.domain import (
    MarketplaceNotificationEvent,
    NotificationDeliveryState,
    NotificationFailureCode,
    RecipientFanoutError,
)
from sky_bridge_jet.modules.notifications.marketplace import (
    CLAIM_LEASE,
    ClaimedNotification,
    DispatchResult,
    MarketplaceNotificationDispatcher,
    MarketplaceNotificationService,
)
from sky_bridge_jet.modules.notifications.models import NotificationOutbox
from sky_bridge_jet.modules.notifications.repositories import NotificationOutboxRepository
from sky_bridge_jet.modules.notifications.services import NotificationOutboxService
from sky_bridge_jet.modules.notifications.worker import dispatch_once
from sky_bridge_jet.modules.offers.domain import OfferStatus
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.offers.services import OperatorOfferService
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
NOW = datetime(2026, 8, 28, 21, tzinfo=UTC)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    test_client = iam_support.integration_client()
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture(scope="module")
def airports(client: TestClient) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        seed_airports(session)
    return client.get("/api/v1/airports").json()


@pytest.fixture(autouse=True)
def clear_notification_outbox() -> Iterator[None]:
    with SessionLocal.begin() as session:
        session.execute(delete(NotificationOutbox))
    yield


def _member(
    *,
    role: OrganizationRole,
    customer_id: UUID | None = None,
    operator_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[UUID, UUID, str]:
    email = f"notify-{uuid4()}@example.test"
    with SessionLocal.begin() as session:
        user = User(
            email=email,
            normalized_email=email,
            status=UserStatus.ACTIVE,
            email_verified_at=NOW,
        )
        session.add(user)
        session.flush()
        if organization_id is None:
            organization = Organization(
                organization_type=(
                    OrganizationType.CUSTOMER
                    if customer_id is not None
                    else OrganizationType.OPERATOR
                ),
                display_name=f"Notification org {uuid4()}",
                customer_id=customer_id,
                operator_id=operator_id,
            )
            session.add(organization)
            session.flush()
            organization_id = organization.id
        session.add(
            OrganizationMembership(
                user_id=user.id,
                organization_id=organization_id,
                role=role,
            )
        )
        session.flush()
        return user.id, organization_id, email


def _members_bulk(*, organization_id: UUID, count: int) -> None:
    with SessionLocal.begin() as session:
        for _ in range(count):
            email = f"notify-{uuid4()}@example.test"
            user = User(
                email=email,
                normalized_email=email,
                status=UserStatus.ACTIVE,
                email_verified_at=NOW,
            )
            session.add(user)
            session.flush()
            session.add(
                OrganizationMembership(
                    user_id=user.id,
                    organization_id=organization_id,
                    role=OrganizationRole.CUSTOMER_ASSISTANT,
                )
            )


def _draft_scenario(client: TestClient, airports: list[dict[str, Any]]) -> dict[str, Any]:
    customer = client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Notification Customer",
            "primary_email": f"commercial-{uuid4()}@example.test",
            "preferred_currency": "EUR",
            "timezone": "Europe/Dublin",
        },
    ).json()
    operator = client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Notification Aviation {uuid4()}",
            "country_code": "IE",
            "contact_email": f"operator-{uuid4()}@example.test",
        },
    ).json()
    aircraft = client.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator["id"],
            "manufacturer": "Cessna",
            "model": "Citation CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 7,
        },
    ).json()
    make_operator_eligible(client, operator["id"], aircraft["id"])
    trip = client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer["id"],
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 2,
                }
            ],
        },
    ).json()
    assert (
        client.post(
            f"/api/v1/trip-requests/{trip['id']}/submit",
            json={"expected_version": trip["version"]},
        ).status_code
        == 200
    )
    offer = client.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip["id"],
            "operator_id": operator["id"],
            "aircraft_id": aircraft["id"],
            "currency": "EUR",
            "operator_amount_minor": 1_000_000,
            "tax_amount_minor": 50_000,
            "valid_until": "2026-12-15T14:00:00+00:00",
        },
    ).json()
    return {"customer": customer, "operator": operator, "trip": trip, "offer": offer}


def _submit_select_book(client: TestClient, scenario: dict[str, Any]) -> dict[str, Any]:
    offer_id = scenario["offer"]["id"]
    trip_id = scenario["trip"]["id"]
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    selection = client.post(f"/api/v1/trip-requests/{trip_id}/offers/{offer_id}/select")
    assert selection.status_code == 200
    response = client.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip_id, "operator_offer_id": offer_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _events_for(resource_ids: set[UUID]) -> list[NotificationOutbox]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(NotificationOutbox)
                .where(NotificationOutbox.resource_id.in_(resource_ids))
                .order_by(NotificationOutbox.event_type, NotificationOutbox.recipient_user_id)
            )
        )


def test_four_event_catalog_recipient_isolation_and_fake_delivery(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    customer_id = UUID(scenario["customer"]["id"])
    operator_id = UUID(scenario["operator"]["id"])
    customer_user, _, customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER, customer_id=customer_id
    )
    admin_user, operator_org, _ = _member(
        role=OrganizationRole.OPERATOR_ADMIN, operator_id=operator_id
    )
    operations_user, _, _ = _member(
        role=OrganizationRole.OPERATOR_OPERATIONS, organization_id=operator_org
    )
    sales_user, _, _ = _member(role=OrganizationRole.OPERATOR_SALES, organization_id=operator_org)
    foreign_customer, _, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(
            client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "Foreign Customer",
                    "primary_email": f"foreign-{uuid4()}@example.test",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            ).json()["id"]
        ),
    )

    booking = _submit_select_book(client, scenario)
    confirm = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "CONFIRMED"

    resource_ids = {UUID(scenario["offer"]["id"]), UUID(booking["id"])}
    intents = _events_for(resource_ids)
    by_event: dict[str, set[UUID]] = {}
    for intent in intents:
        by_event.setdefault(intent.event_type, set()).add(intent.recipient_user_id)
    assert by_event == {
        MarketplaceNotificationEvent.OFFER_AVAILABLE.value: {customer_user},
        MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION.value: {
            admin_user,
            operations_user,
        },
        MarketplaceNotificationEvent.BOOKING_CONFIRMED.value: {customer_user},
    }
    assert sales_user not in {row.recipient_user_id for row in intents}
    assert foreign_customer not in {row.recipient_user_id for row in intents}
    assert len({row.dedupe_key for row in intents}) == len(intents)

    with SessionLocal() as session:
        booking_before = session.get_one(Booking, UUID(booking["id"])).status
        payment_count = session.scalar(select(func.count()).select_from(Payment))
        operation_count = session.scalar(select(func.count()).select_from(PaymentOperation))
    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(
            session,
            sender,
            Settings(app_environment="test", web_public_origin="https://portal.example.test"),
        ).dispatch_batch(now=NOW, limit=10)
    assert result.claimed == 4
    assert result.delivered == 1
    assert result.permanent_failed == 3
    assert result.retryable_failed == result.stale_results == 0
    # Selection supersedes OFFER_AVAILABLE and confirmation supersedes both operator
    # pending intents; only the current CONFIRMED customer notification is delivered.
    assert {message.recipient for message in sender.accepted} == {customer_email}
    rendered = " ".join(message.text_body for message in sender.accepted).lower()
    assert "passenger" not in rendered
    assert "payment" not in rendered
    assert "refund" not in rendered
    assert "https://portal.example.test" in rendered
    with SessionLocal() as session:
        assert session.get_one(Booking, UUID(booking["id"])).status is booking_before
        assert session.scalar(select(func.count()).select_from(Payment)) == payment_count
        assert session.scalar(select(func.count()).select_from(PaymentOperation)) == operation_count


def test_rejected_event_and_delivery_failure_do_not_change_business_state(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    customer_user, _, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    booking = _submit_select_book(client, scenario)
    response = client.post(
        f"/api/v1/bookings/{booking['id']}/reject",
        json={"operator_id": scenario["operator"]["id"], "reason": "OTHER"},
    )
    assert response.status_code == 200
    rows = _events_for({UUID(booking["id"])})
    rejected = [
        row for row in rows if row.event_type == MarketplaceNotificationEvent.BOOKING_REJECTED
    ]
    assert len(rejected) == 1
    assert rejected[0].recipient_user_id == customer_user

    sender = FakeMarketplaceNotificationSender(mode=FakeDeliveryMode.PERMANENT_FAILURE)
    with SessionLocal() as session:
        MarketplaceNotificationDispatcher(session, sender).dispatch_batch(now=NOW, limit=100)
    with SessionLocal() as session:
        assert session.get_one(Booking, UUID(booking["id"])).status is BookingStatus.REJECTED
        final = session.get_one(NotificationOutbox, rejected[0].id)
        assert final.delivery_state is NotificationDeliveryState.FAILED_PERMANENT
        assert final.failure_code == "INVALID_RECIPIENT"


@pytest.mark.parametrize("command", ["confirm", "reject"])
def test_required_intent_failure_rolls_back_booking_transition(
    client: TestClient,
    airports: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    booking = _submit_select_book(client, scenario)

    def fail(*_args: object, **_kwargs: object) -> list[NotificationOutbox]:
        raise RuntimeError("forced outbox failure")

    method = f"record_booking_{'confirmed' if command == 'confirm' else 'rejected'}"
    monkeypatch.setattr(MarketplaceNotificationService, method, fail)
    body = (
        {"operator_id": scenario["operator"]["id"]}
        if command == "confirm"
        else {"operator_id": scenario["operator"]["id"], "reason": "OTHER"}
    )
    with pytest.raises(RuntimeError, match="forced outbox failure"):
        client.post(f"/api/v1/bookings/{booking['id']}/{command}", json=body)
    with SessionLocal() as session:
        assert (
            session.get_one(Booking, UUID(booking["id"])).status
            is BookingStatus.PENDING_OPERATOR_CONFIRMATION
        )
        event_type = (
            MarketplaceNotificationEvent.BOOKING_CONFIRMED
            if command == "confirm"
            else MarketplaceNotificationEvent.BOOKING_REJECTED
        )
        assert (
            session.scalar(
                select(func.count()).where(
                    NotificationOutbox.resource_id == UUID(booking["id"]),
                    NotificationOutbox.event_type == event_type.value,
                )
            )
            == 0
        )


def test_retry_backoff_limit_restart_and_email_change(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    user_id, _, original_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    assert client.post(f"/api/v1/offers/{scenario['offer']['id']}/submit").status_code == 200
    row = _events_for({UUID(scenario["offer"]["id"])})[0]
    changed_email = f"changed-{uuid4()}@example.test"
    with SessionLocal.begin() as session:
        user = session.get_one(User, user_id)
        user.email = changed_email
        user.normalized_email = changed_email

    transient = FakeMarketplaceNotificationSender(mode=FakeDeliveryMode.TRANSIENT_FAILURE)
    with SessionLocal() as session:
        first = MarketplaceNotificationDispatcher(session, transient).dispatch_batch(
            now=NOW, limit=1
        )
    assert first.retryable_failed == 1
    assert transient.attempts[0].recipient == changed_email
    assert transient.attempts[0].recipient != original_email
    with SessionLocal() as session:
        after_first = session.get_one(NotificationOutbox, row.id)
        assert after_first.attempt_count == 1
        assert after_first.next_attempt_at == NOW + timedelta(minutes=5)

    with SessionLocal() as fresh_session:
        assert (
            MarketplaceNotificationDispatcher(fresh_session, transient)
            .dispatch_batch(now=NOW + timedelta(minutes=4), limit=1)
            .claimed
            == 0
        )
    with SessionLocal() as fresh_session:
        second = MarketplaceNotificationDispatcher(fresh_session, transient).dispatch_batch(
            now=NOW + timedelta(minutes=5), limit=1
        )
    assert second.retryable_failed == 1
    with SessionLocal() as session:
        after_second = session.get_one(NotificationOutbox, row.id)
        assert after_second.attempt_count == 2
        assert after_second.next_attempt_at == NOW + timedelta(minutes=35)
    with SessionLocal() as fresh_session:
        third = MarketplaceNotificationDispatcher(fresh_session, transient).dispatch_batch(
            now=NOW + timedelta(minutes=35), limit=1
        )
    assert third.permanent_failed == 1
    with SessionLocal() as session:
        final = session.get_one(NotificationOutbox, row.id)
        assert final.delivery_state is NotificationDeliveryState.FAILED_PERMANENT
        assert final.id == row.id
        assert final.attempt_count == 3


def test_disabled_worker_preserves_durable_notification(
    client: TestClient, airports: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _draft_scenario(client, airports)
    _, customer_org, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _members_bulk(organization_id=customer_org, count=2)
    offer_id = UUID(scenario["offer"]["id"])
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    rows = _events_for({offer_id})
    assert len(rows) == 3
    with SessionLocal.begin() as session:
        retryable = session.get_one(NotificationOutbox, rows[1].id)
        retryable.delivery_state = NotificationDeliveryState.FAILED_RETRYABLE
        retryable.attempt_count = 1
        retryable.next_attempt_at = NOW - timedelta(minutes=1)
        expired = session.get_one(NotificationOutbox, rows[2].id)
        expired.delivery_state = NotificationDeliveryState.CLAIMED
        expired.attempt_count = 1
        expired.claim_token = uuid4()
        expired.claimed_at = NOW - CLAIM_LEASE - timedelta(seconds=1)
    with SessionLocal() as session:
        before = {
            row.id: (
                session.get_one(NotificationOutbox, row.id).delivery_state,
                session.get_one(NotificationOutbox, row.id).attempt_count,
                session.get_one(NotificationOutbox, row.id).claim_token,
                session.get_one(NotificationOutbox, row.id).claimed_at,
            )
            for row in rows
        }
    monkeypatch.setenv("MARKETPLACE_EMAIL_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert dispatch_once() == 0
    finally:
        get_settings.cache_clear()
    with SessionLocal() as session:
        after_disabled = {
            row.id: (
                session.get_one(NotificationOutbox, row.id).delivery_state,
                session.get_one(NotificationOutbox, row.id).attempt_count,
                session.get_one(NotificationOutbox, row.id).claim_token,
                session.get_one(NotificationOutbox, row.id).claimed_at,
            )
            for row in rows
        }
        assert after_disabled == before
        assert all(
            session.get_one(NotificationOutbox, row.id).provider_message_id is None for row in rows
        )
    monkeypatch.setenv("MARKETPLACE_EMAIL_ENABLED", "true")
    monkeypatch.setenv("MARKETPLACE_EMAIL_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        assert dispatch_once() == 3
    finally:
        get_settings.cache_clear()
    with SessionLocal() as session:
        assert {session.get_one(NotificationOutbox, row.id).delivery_state for row in rows} == {
            NotificationDeliveryState.DELIVERED
        }


def test_systemic_provider_failure_stops_batch_without_burning_rows(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _, customer_org, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _members_bulk(organization_id=customer_org, count=2)
    offer_id = UUID(scenario["offer"]["id"])
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    rows = _events_for({offer_id})
    assert len(rows) == 3
    with SessionLocal.begin() as session:
        for row in rows:
            session.get_one(NotificationOutbox, row.id).attempt_count = 2

    class SystemicSender:
        attempts = 0

        def send(self, _message: MarketplaceEmail) -> NoReturn:
            self.attempts += 1
            raise NotificationDeliveryError(
                NotificationFailureCode.PROVIDER_SYSTEMIC_AUTH,
                retryable=True,
                systemic=True,
            )

    sender = SystemicSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender).dispatch_batch(now=NOW, limit=3)
    assert result == DispatchResult(
        claimed=3,
        delivered=0,
        retryable_failed=3,
        permanent_failed=0,
        stale_results=0,
    )
    assert sender.attempts == 1
    with SessionLocal() as session:
        persisted = list(
            session.scalars(
                select(NotificationOutbox).where(NotificationOutbox.id.in_([r.id for r in rows]))
            )
        )
        assert {row.delivery_state for row in persisted} == {
            NotificationDeliveryState.FAILED_RETRYABLE
        }
        assert {row.failure_code for row in persisted} == {"PROVIDER_SYSTEMIC_AUTH"}


def test_revoked_operator_membership_fails_permanently_before_send(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    user_id, organization_id, revoked_email = _member(
        role=OrganizationRole.OPERATOR_OPERATIONS,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    booking = _submit_select_book(client, scenario)
    with SessionLocal.begin() as session:
        membership = session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
        assert membership is not None
        membership.status = MembershipStatus.REVOKED
        membership.revoked_at = NOW
    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        MarketplaceNotificationDispatcher(session, sender).dispatch_batch(now=NOW, limit=100)
    pending = [
        row
        for row in _events_for({UUID(booking["id"])})
        if row.event_type
        == MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION.value
    ]
    assert len(pending) == 1
    assert pending[0].delivery_state is NotificationDeliveryState.FAILED_PERMANENT
    assert pending[0].failure_code == "RECIPIENT_INELIGIBLE"
    assert revoked_email not in {message.recipient for message in sender.attempts}


def test_recipient_resolution_query_count_is_fixed_for_one_twenty_and_hundred(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _, customer_org, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _members_bulk(organization_id=customer_org, count=99)
    assert client.post(f"/api/v1/offers/{scenario['offer']['id']}/submit").status_code == 200
    rows = _events_for({UUID(scenario["offer"]["id"])})
    assert len(rows) == 100

    for count in (1, 20, 100):
        snapshots = [
            ClaimedNotification(
                id=row.id,
                claim_token=uuid4(),
                event=MarketplaceNotificationEvent(row.event_type),
                recipient_user_id=row.recipient_user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                attempt_count=1,
            )
            for row in rows[:count]
        ]
        statements = 0

        def count_statement(*_args: object) -> None:
            nonlocal statements
            statements += 1

        with SessionLocal() as session:
            connection = session.connection()
            event.listen(connection, "before_cursor_execute", count_statement)
            try:
                resolved = MarketplaceNotificationDispatcher(
                    session, FakeMarketplaceNotificationSender()
                )._resolve_recipients(snapshots)
            finally:
                event.remove(connection, "before_cursor_execute", count_statement)
        assert len(resolved) == count
        assert statements == 2


def test_stale_dispatch_result_cannot_finalize_reclaimed_row(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    assert client.post(f"/api/v1/offers/{scenario['offer']['id']}/submit").status_code == 200
    with SessionLocal.begin() as session:
        first = NotificationOutboxRepository(session).claim_batch(
            now=NOW, lease_expires_before=NOW - CLAIM_LEASE, limit=1
        )[0]
        assert first.claim_token is not None
        stale = ClaimedNotification(
            id=first.id,
            claim_token=first.claim_token,
            event=MarketplaceNotificationEvent(first.event_type),
            recipient_user_id=first.recipient_user_id,
            resource_type=first.resource_type,
            resource_id=first.resource_id,
            attempt_count=first.attempt_count,
        )
    with SessionLocal.begin() as session:
        second = NotificationOutboxRepository(session).claim_batch(
            now=NOW + CLAIM_LEASE + timedelta(seconds=1),
            lease_expires_before=NOW + timedelta(seconds=1),
            limit=1,
        )[0]
        assert second.claim_token != stale.claim_token
    with SessionLocal() as session:
        dispatcher = MarketplaceNotificationDispatcher(session, FakeMarketplaceNotificationSender())
        assert not dispatcher._mark_delivered(stale, NOW + CLAIM_LEASE + timedelta(seconds=2))
    with SessionLocal() as session:
        authoritative = session.get_one(NotificationOutbox, stale.id)
        assert authoritative.delivery_state is NotificationDeliveryState.CLAIMED
        assert authoritative.claim_token == second.claim_token


def test_offer_and_partial_booking_intent_failures_roll_back_business_transaction(
    client: TestClient,
    airports: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offer_scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(offer_scenario["customer"]["id"]),
    )

    def fail_offer(*_args: object, **_kwargs: object) -> list[NotificationOutbox]:
        raise RuntimeError("forced offer outbox failure")

    monkeypatch.setattr(MarketplaceNotificationService, "record_offer_available", fail_offer)
    with pytest.raises(RuntimeError, match="forced offer outbox failure"):
        client.post(f"/api/v1/offers/{offer_scenario['offer']['id']}/submit")
    with SessionLocal() as session:
        assert (
            session.get_one(OperatorOffer, UUID(offer_scenario["offer"]["id"])).status
            is OfferStatus.DRAFT
        )
        assert not _events_for({UUID(offer_scenario["offer"]["id"])})

    monkeypatch.undo()
    booking_scenario = _draft_scenario(client, airports)
    operator_id = UUID(booking_scenario["operator"]["id"])
    _, operator_org, _ = _member(role=OrganizationRole.OPERATOR_ADMIN, operator_id=operator_id)
    _member(role=OrganizationRole.OPERATOR_OPERATIONS, organization_id=operator_org)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(booking_scenario["customer"]["id"]),
    )
    offer_id = booking_scenario["offer"]["id"]
    trip_id = booking_scenario["trip"]["id"]
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    assert (
        client.post(f"/api/v1/trip-requests/{trip_id}/offers/{offer_id}/select").status_code == 200
    )

    def fail_after_first(
        service: MarketplaceNotificationService,
        event_type: MarketplaceNotificationEvent,
        resource_type: str,
        resource_id: UUID,
        recipients: list[UUID],
    ) -> list[NotificationOutbox]:
        service.outbox.create_intent(
            dedupe_key=f"{event_type.value}:{resource_id}:{recipients[0]}",
            event_type=event_type.value,
            recipient_user_id=recipients[0],
            resource_type=resource_type,
            resource_id=resource_id,
        )
        raise RuntimeError("forced partial recipient failure")

    monkeypatch.setattr(MarketplaceNotificationService, "_record", fail_after_first)
    with pytest.raises(RuntimeError, match="forced partial recipient failure"):
        client.post(
            "/api/v1/bookings",
            json={"trip_request_id": trip_id, "operator_offer_id": offer_id},
        )
    with SessionLocal() as session:
        assert (
            session.scalar(select(func.count()).where(Booking.operator_offer_id == UUID(offer_id)))
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).where(
                    NotificationOutbox.event_type
                    == MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION.value,
                    NotificationOutbox.resource_type == "BOOKING",
                )
            )
            == 0
        )


def test_unknown_delivery_result_is_retryable_without_new_logical_intent(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    assert client.post(f"/api/v1/offers/{scenario['offer']['id']}/submit").status_code == 200
    row = _events_for({UUID(scenario["offer"]["id"])})[0]
    sender = FakeMarketplaceNotificationSender(mode=FakeDeliveryMode.ACCEPTED_UNKNOWN)
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender).dispatch_batch(now=NOW, limit=1)
    assert result.retryable_failed == 1
    assert len(sender.accepted) == len(sender.attempts) == 1
    with SessionLocal() as session:
        authoritative = session.get_one(NotificationOutbox, row.id)
        assert authoritative.delivery_state is NotificationDeliveryState.FAILED_RETRYABLE
        assert authoritative.failure_code == "UNKNOWN_DELIVERY_RESULT"
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 1


def test_dispatcher_bounds_unknown_event_and_concurrent_claim(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    recipient, _, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    with SessionLocal.begin() as session:
        NotificationOutboxService(session).create_intent(
            dedupe_key=f"UNKNOWN:{scenario['offer']['id']}:{recipient}",
            event_type="UNKNOWN_TRUSTED_EVENT",
            recipient_user_id=recipient,
            resource_type="OFFER",
            resource_id=UUID(scenario["offer"]["id"]),
        )
    unknown_sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        dispatcher = MarketplaceNotificationDispatcher(session, unknown_sender)
        with pytest.raises(ValueError, match="between 1 and 100"):
            dispatcher.dispatch_batch(now=NOW, limit=101)
        result = dispatcher.dispatch_batch(now=NOW, limit=1)
    assert result.permanent_failed == 1
    assert not unknown_sender.attempts

    with SessionLocal.begin() as session:
        session.execute(delete(NotificationOutbox))
    assert client.post(f"/api/v1/offers/{scenario['offer']['id']}/submit").status_code == 200
    barrier = threading.Barrier(2)
    senders = [FakeMarketplaceNotificationSender(), FakeMarketplaceNotificationSender()]

    def run(index: int) -> DispatchResult:
        barrier.wait()
        with SessionLocal() as session:
            return MarketplaceNotificationDispatcher(session, senders[index]).dispatch_batch(
                now=NOW, limit=1
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, range(2)))
    assert sum(result.claimed for result in results) == 1
    assert sum(result.delivered for result in results) == 1
    assert sum(len(sender.attempts) for sender in senders) == 1


def test_withdrawn_offer_intent_fails_closed_before_delivery(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _, _, customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    offer_id = scenario["offer"]["id"]
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    withdrawn = client.post(f"/api/v1/offers/{offer_id}/withdraw")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"

    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender).dispatch_batch(
            now=NOW, limit=100
        )
    assert customer_email not in {message.recipient for message in sender.attempts}
    assert result.permanent_failed == 1
    row = _events_for({UUID(offer_id)})[0]
    assert row.delivery_state is NotificationDeliveryState.FAILED_PERMANENT
    assert row.failure_code == "EVENT_NO_LONGER_APPLICABLE"


def test_resolved_booking_pending_intent_fails_closed_before_delivery(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _, _, operator_email = _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    booking = _submit_select_book(client, scenario)
    response = client.post(
        f"/api/v1/bookings/{booking['id']}/confirm",
        json={"operator_id": scenario["operator"]["id"]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"

    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender).dispatch_batch(
            now=NOW, limit=100
        )
    assert operator_email not in {message.recipient for message in sender.attempts}
    # The selected Offer availability intent in the same canonical flow is also stale.
    assert result.permanent_failed >= 1
    pending = [
        row
        for row in _events_for({UUID(booking["id"])})
        if row.event_type
        == MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION.value
    ]
    assert len(pending) == 1
    assert pending[0].delivery_state is NotificationDeliveryState.FAILED_PERMANENT
    assert pending[0].failure_code == "EVENT_NO_LONGER_APPLICABLE"


@pytest.mark.parametrize("stale_state", ["SELECTED", "EXPIRED"])
def test_selected_or_expired_offer_intent_fails_closed(
    client: TestClient, airports: list[dict[str, Any]], stale_state: str
) -> None:
    scenario = _draft_scenario(client, airports)
    _, _, customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    offer_id = scenario["offer"]["id"]
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    if stale_state == "SELECTED":
        trip_id = scenario["trip"]["id"]
        assert (
            client.post(f"/api/v1/trip-requests/{trip_id}/offers/{offer_id}/select").status_code
            == 200
        )
    else:
        with SessionLocal.begin() as session:
            session.get_one(OperatorOffer, UUID(offer_id)).valid_until = NOW - timedelta(seconds=1)

    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender).dispatch_batch(
            now=NOW, limit=100
        )
    assert result.permanent_failed == 1
    assert customer_email not in {message.recipient for message in sender.attempts}
    row = _events_for({UUID(offer_id)})[0]
    assert row.failure_code == "EVENT_NO_LONGER_APPLICABLE"


def test_valid_submitted_offer_and_still_pending_booking_deliver(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _, _, customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _, _, operator_email = _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    booking = _submit_select_book(client, scenario)
    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, sender).dispatch_batch(
            now=NOW, limit=100
        )
    # Selection supersedes the availability intent, while the Booking remains pending.
    assert result.delivered == 1
    assert result.permanent_failed == 1
    assert {message.recipient for message in sender.accepted} == {operator_email}
    assert customer_email not in {message.recipient for message in sender.attempts}
    assert booking["status"] == "PENDING_OPERATOR_CONFIRMATION"

    offer_only = _draft_scenario(client, airports)
    _, _, valid_offer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(offer_only["customer"]["id"]),
    )
    assert client.post(f"/api/v1/offers/{offer_only['offer']['id']}/submit").status_code == 200
    second_sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        result = MarketplaceNotificationDispatcher(session, second_sender).dispatch_batch(
            now=NOW, limit=100
        )
    assert result.delivered == 1
    assert {message.recipient for message in second_sender.accepted} == {valid_offer_email}


@pytest.mark.parametrize("terminal_command", ["reject", "cancel"])
def test_rejected_or_cancelled_booking_suppresses_old_pending_intent(
    client: TestClient, airports: list[dict[str, Any]], terminal_command: str
) -> None:
    scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _, _, operator_email = _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    booking = _submit_select_book(client, scenario)
    if terminal_command == "reject":
        response = client.post(
            f"/api/v1/bookings/{booking['id']}/reject",
            json={"operator_id": scenario["operator"]["id"], "reason": "OTHER"},
        )
    else:
        response = client.post(
            f"/api/v1/bookings/{booking['id']}/cancel",
            json={"actor": "CUSTOMER", "reason": "NO_LONGER_REQUIRED"},
        )
    assert response.status_code == 200
    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        MarketplaceNotificationDispatcher(session, sender).dispatch_batch(now=NOW, limit=100)
    assert operator_email not in {message.recipient for message in sender.attempts}
    pending = [
        row
        for row in _events_for({UUID(booking["id"])})
        if row.event_type
        == MarketplaceNotificationEvent.BOOKING_PENDING_OPERATOR_CONFIRMATION.value
    ][0]
    assert pending.failure_code == "EVENT_NO_LONGER_APPLICABLE"


def test_confirmed_intent_becomes_stale_after_cancellation_and_rejected_remains_factual(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    confirmed_scenario = _draft_scenario(client, airports)
    _, _, confirmed_customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(confirmed_scenario["customer"]["id"]),
    )
    _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(confirmed_scenario["operator"]["id"]),
    )
    confirmed_booking = _submit_select_book(client, confirmed_scenario)
    assert (
        client.post(
            f"/api/v1/bookings/{confirmed_booking['id']}/confirm",
            json={"operator_id": confirmed_scenario["operator"]["id"]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/bookings/{confirmed_booking['id']}/cancel",
            json={"actor": "CUSTOMER", "reason": "NO_LONGER_REQUIRED"},
        ).status_code
        == 200
    )

    rejected_scenario = _draft_scenario(client, airports)
    _, _, rejected_customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(rejected_scenario["customer"]["id"]),
    )
    _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(rejected_scenario["operator"]["id"]),
    )
    rejected_booking = _submit_select_book(client, rejected_scenario)
    assert (
        client.post(
            f"/api/v1/bookings/{rejected_booking['id']}/reject",
            json={"operator_id": rejected_scenario["operator"]["id"], "reason": "OTHER"},
        ).status_code
        == 200
    )
    sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        MarketplaceNotificationDispatcher(session, sender).dispatch_batch(now=NOW, limit=100)
    recipients = {message.recipient for message in sender.accepted}
    assert confirmed_customer_email not in recipients
    assert rejected_customer_email in recipients


def test_retry_revalidates_lifecycle_and_missing_resource_fails_closed(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    user_id, _, customer_email = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    offer_id = scenario["offer"]["id"]
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    transient = FakeMarketplaceNotificationSender(mode=FakeDeliveryMode.TRANSIENT_FAILURE)
    with SessionLocal() as session:
        first = MarketplaceNotificationDispatcher(session, transient).dispatch_batch(
            now=NOW, limit=1
        )
    assert first.retryable_failed == 1
    assert client.post(f"/api/v1/offers/{offer_id}/withdraw").status_code == 200
    success = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        retry = MarketplaceNotificationDispatcher(session, success).dispatch_batch(
            now=NOW + timedelta(minutes=5), limit=1
        )
    assert retry.permanent_failed == 1
    assert customer_email not in {message.recipient for message in success.attempts}
    row = _events_for({UUID(offer_id)})[0]
    assert row.attempt_count == 2
    assert row.failure_code == "EVENT_NO_LONGER_APPLICABLE"

    missing_id = uuid4()
    with SessionLocal.begin() as session:
        NotificationOutboxService(session).create_intent(
            dedupe_key=f"OFFER_AVAILABLE:{missing_id}:{user_id}",
            event_type=MarketplaceNotificationEvent.OFFER_AVAILABLE.value,
            recipient_user_id=user_id,
            resource_type="OFFER",
            resource_id=missing_id,
        )
    missing_sender = FakeMarketplaceNotificationSender()
    with SessionLocal() as session:
        missing = MarketplaceNotificationDispatcher(session, missing_sender).dispatch_batch(
            now=NOW + timedelta(minutes=6), limit=1
        )
    assert missing.permanent_failed == 1
    assert not missing_sender.attempts


def test_applicability_query_count_is_fixed_for_one_twenty_and_hundred(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _, customer_org, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _members_bulk(organization_id=customer_org, count=99)
    offer_id = scenario["offer"]["id"]
    assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    rows = _events_for({UUID(offer_id)})
    assert len(rows) == 100
    for count in (1, 20, 100):
        snapshots = [
            ClaimedNotification(
                id=row.id,
                claim_token=uuid4(),
                event=MarketplaceNotificationEvent.OFFER_AVAILABLE,
                recipient_user_id=row.recipient_user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                attempt_count=1,
            )
            for row in rows[:count]
        ]
        statements = 0

        def count_statement(*_args: object) -> None:
            nonlocal statements
            statements += 1

        with SessionLocal() as session:
            connection = session.connection()
            event.listen(connection, "before_cursor_execute", count_statement)
            try:
                applicable = MarketplaceNotificationDispatcher(
                    session, FakeMarketplaceNotificationSender()
                )._applicable_notification_ids(snapshots, now=NOW)
            finally:
                event.remove(connection, "before_cursor_execute", count_statement)
        assert len(applicable) == count
        assert statements == 1


def test_offer_notification_fanout_over_one_hundred_fails_without_partial_state(
    client: TestClient, airports: list[dict[str, Any]]
) -> None:
    scenario = _draft_scenario(client, airports)
    _, customer_org, _ = _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _members_bulk(organization_id=customer_org, count=100)
    offer_id = UUID(scenario["offer"]["id"])

    with SessionLocal() as session:
        with pytest.raises(RecipientFanoutError):
            OperatorOfferService(session).submit(offer_id)

    with SessionLocal() as session:
        offer = session.get(OperatorOffer, offer_id)
        assert offer is not None
        assert offer.status is OfferStatus.DRAFT
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(NotificationOutbox.resource_id == offer_id)
            )
            == 0
        )


@pytest.mark.parametrize("resource", ["offer", "booking"])
def test_committed_lifecycle_change_after_claim_is_rechecked_before_send(
    client: TestClient, airports: list[dict[str, Any]], resource: str
) -> None:
    scenario = _draft_scenario(client, airports)
    _member(
        role=OrganizationRole.CUSTOMER_OWNER,
        customer_id=UUID(scenario["customer"]["id"]),
    )
    _member(
        role=OrganizationRole.OPERATOR_ADMIN,
        operator_id=UUID(scenario["operator"]["id"]),
    )
    offer_id = scenario["offer"]["id"]
    booking_id: str | None = None
    if resource == "offer":
        assert client.post(f"/api/v1/offers/{offer_id}/submit").status_code == 200
    else:
        booking = _submit_select_book(client, scenario)
        booking_id = booking["id"]

    def transition() -> Any:
        if booking_id is not None:
            return client.post(
                f"/api/v1/bookings/{booking_id}/confirm",
                json={"operator_id": scenario["operator"]["id"]},
            )
        return client.post(f"/api/v1/offers/{offer_id}/withdraw")

    claimed = threading.Event()
    continue_resolution = threading.Event()
    sender = FakeMarketplaceNotificationSender()

    class PausingDispatcher(MarketplaceNotificationDispatcher):
        def _resolve_recipients(self, notifications: list[ClaimedNotification]) -> dict[UUID, str]:
            resolved = super()._resolve_recipients(notifications)
            claimed.set()
            assert continue_resolution.wait(timeout=5)
            return resolved

    def dispatch() -> DispatchResult:
        with SessionLocal() as session:
            return PausingDispatcher(session, sender).dispatch_batch(now=NOW, limit=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(dispatch)
        assert claimed.wait(timeout=5)
        response = transition()
        assert response.status_code == 200, response.text
        continue_resolution.set()
        result = future.result(timeout=5)

    assert result.permanent_failed == 1
    assert not sender.attempts
