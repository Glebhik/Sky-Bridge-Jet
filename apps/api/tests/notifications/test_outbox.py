from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DataError, IntegrityError

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.iam.models import User
from sky_bridge_jet.modules.notifications.domain import (
    NotificationClaimConflictError,
    NotificationDedupeConflictError,
    NotificationDeliveryState,
)
from sky_bridge_jet.modules.notifications.models import NotificationOutbox
from sky_bridge_jet.modules.notifications.repositories import NotificationOutboxRepository
from sky_bridge_jet.modules.notifications.services import NotificationOutboxService

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


@pytest.fixture
def recipient_id() -> UUID:
    with SessionLocal.begin() as session:
        session.execute(delete(NotificationOutbox))
        email = f"outbox-{uuid4()}@example.test"
        user = User(email=email, normalized_email=email)
        session.add(user)
        session.flush()
        return user.id


def _create(session, recipient_id: UUID, suffix: str = "1") -> NotificationOutbox:
    resource_id = uuid5(NAMESPACE_URL, f"notification-test:{suffix}:{recipient_id}")
    return NotificationOutboxService(session).create_intent(
        dedupe_key=f"BOOKING_CONFIRMED:{suffix}:{recipient_id}",
        event_type="BOOKING_CONFIRMED",
        recipient_user_id=recipient_id,
        resource_type="BOOKING",
        resource_id=resource_id,
    )


def _seed_mixed_queue(session, recipient_id: UUID, row_count: int) -> None:
    session.execute(
        text(
            """
            INSERT INTO notification_outbox (
                id, dedupe_key, event_type, recipient_user_id, resource_type, resource_id,
                delivery_state, attempt_count, claim_token, claimed_at, next_attempt_at,
                last_attempt_at, delivered_at, failure_code, created_at, updated_at
            )
            SELECT
                ('00000000-0000-0000-0001-' || lpad(to_hex(gs), 12, '0'))::uuid,
                'PLAN:' || gs, 'BOOKING_CONFIRMED', :recipient_id, 'BOOKING',
                ('00000000-0000-0000-0002-' || lpad(to_hex(gs), 12, '0'))::uuid,
                (CASE gs % 7
                    WHEN 0 THEN 'PENDING'
                    WHEN 1 THEN 'FAILED_RETRYABLE'
                    WHEN 2 THEN 'FAILED_RETRYABLE'
                    WHEN 3 THEN 'CLAIMED'
                    WHEN 4 THEN 'CLAIMED'
                    WHEN 5 THEN 'DELIVERED'
                    ELSE 'FAILED_PERMANENT'
                END)::notification_delivery_state,
                CASE WHEN gs % 7 IN (1, 2, 3, 4, 5, 6) THEN 1 ELSE 0 END,
                CASE WHEN gs % 7 IN (3, 4)
                    THEN ('00000000-0000-0000-0003-' || lpad(to_hex(gs), 12, '0'))::uuid
                END,
                CASE WHEN gs % 7 = 3 THEN :now - interval '20 minutes'
                     WHEN gs % 7 = 4 THEN :now - interval '1 minute' END,
                CASE WHEN gs % 7 = 1 THEN :now - interval '10 minutes'
                     WHEN gs % 7 = 2 THEN :now + interval '1 day' END,
                CASE WHEN gs % 7 IN (1, 2, 3, 4, 5, 6) THEN :now - interval '1 day' END,
                CASE WHEN gs % 7 = 5 THEN :now - interval '1 hour' END,
                CASE WHEN gs % 7 IN (1, 2, 6) THEN 'SEEDED' END,
                :now - (gs * interval '1 second'),
                :now - (gs * interval '1 second')
            FROM generate_series(1, :row_count) AS gs
            """
        ),
        {"recipient_id": recipient_id, "now": NOW, "row_count": row_count},
    )


@requires_db
def test_create_is_idempotent_and_transaction_neutral(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        user = session.get_one(User, recipient_id)
        user.display_name = "Committed business mutation"
        first = _create(session, recipient_id)
        second = _create(session, recipient_id)
        assert first.id == second.id
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 1
        assert session.get_one(User, recipient_id).display_name == "Committed business mutation"
    with pytest.raises(RuntimeError):
        with SessionLocal.begin() as session:
            session.get_one(User, recipient_id).display_name = "Must roll back"
            _create(session, recipient_id, "rollback")
            raise RuntimeError("business mutation failed")
    with SessionLocal() as session:
        assert session.get_one(User, recipient_id).display_name == "Committed business mutation"
        assert (
            session.scalar(
                select(func.count()).where(NotificationOutbox.dedupe_key.like("%rollback%"))
            )
            == 0
        )


@requires_db
def test_dedupe_collision_with_different_facts_fails_closed(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        original = _create(session, recipient_id)
        with pytest.raises(NotificationDedupeConflictError):
            NotificationOutboxService(session).create_intent(
                dedupe_key=original.dedupe_key,
                event_type="BOOKING_REJECTED",
                recipient_user_id=recipient_id,
                resource_type="BOOKING",
                resource_id=original.resource_id,
            )


@requires_db
def test_bounded_due_discovery_and_state_exclusions(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        rows = [_create(session, recipient_id, str(index)) for index in range(105)]
        rows[0].delivery_state = NotificationDeliveryState.DELIVERED
        rows[1].delivery_state = NotificationDeliveryState.FAILED_PERMANENT
        rows[2].delivery_state = NotificationDeliveryState.FAILED_RETRYABLE
        rows[2].next_attempt_at = NOW + timedelta(hours=1)
    with SessionLocal() as session:
        repository = NotificationOutboxRepository(session)
        found = repository.list_eligible(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=20
        )
        assert len(found) == 20
        assert all(row.delivery_state is NotificationDeliveryState.PENDING for row in found)
        with pytest.raises(ValueError):
            repository.list_eligible(now=NOW, lease_expires_before=NOW, limit=101)


@requires_db
def test_claim_success_failure_and_stale_token(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        row = _create(session, recipient_id)
    with SessionLocal.begin() as session:
        claimed = NotificationOutboxRepository(session).claim_batch(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=1
        )[0]
        first_token = claimed.claim_token
        assert first_token is not None
        assert claimed.attempt_count == 1
    with SessionLocal.begin() as session:
        failed = NotificationOutboxService(session).mark_delivery_failed(
            row.id,
            first_token,
            now=NOW,
            retryable=True,
            failure_code="PROVIDER_UNAVAILABLE",
            next_attempt_at=NOW + timedelta(minutes=1),
        )
        assert failed.delivery_state is NotificationDeliveryState.FAILED_RETRYABLE
    with SessionLocal.begin() as session:
        second = NotificationOutboxRepository(session).claim_batch(
            now=NOW + timedelta(minutes=2),
            lease_expires_before=NOW - timedelta(minutes=3),
            limit=1,
        )[0]
        second_token = second.claim_token
        assert second_token is not None and second_token != first_token
        assert second.attempt_count == 2
    with SessionLocal.begin() as session:
        with pytest.raises(NotificationClaimConflictError):
            NotificationOutboxService(session).mark_delivered(row.id, first_token, now=NOW)
        delivered = NotificationOutboxService(session).mark_delivered(
            row.id, second_token, now=NOW + timedelta(minutes=2)
        )
        assert delivered.delivery_state is NotificationDeliveryState.DELIVERED


@requires_db
def test_expired_claim_is_recovered_after_restart(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        row = _create(session, recipient_id)
    with SessionLocal.begin() as session:
        first = NotificationOutboxRepository(session).claim_batch(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=1
        )[0]
        old_token = first.claim_token
    with SessionLocal.begin() as fresh_session:
        recovered = NotificationOutboxRepository(fresh_session).claim_batch(
            now=NOW + timedelta(minutes=10),
            lease_expires_before=NOW + timedelta(minutes=5),
            limit=1,
        )[0]
        assert recovered.id == row.id
        assert recovered.claim_token != old_token
        assert recovered.attempt_count == 2


@requires_db
def test_concurrent_claim_has_one_owner(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        row = _create(session, recipient_id)
    barrier = threading.Barrier(2)
    claimed: list[tuple[UUID, UUID | None]] = []
    lock = threading.Lock()

    def worker() -> None:
        with SessionLocal.begin() as session:
            barrier.wait()
            result = NotificationOutboxRepository(session).claim_batch(
                now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=1
            )
            with lock:
                claimed.extend((item.id, item.claim_token) for item in result)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(claimed) == 1
    assert claimed[0][0] == row.id
    assert claimed[0][1] is not None


@requires_db
def test_concurrent_dedupe_converges_to_one_row(recipient_id: UUID) -> None:
    barrier = threading.Barrier(2)
    ids: list[UUID] = []
    lock = threading.Lock()

    def worker() -> None:
        with SessionLocal.begin() as session:
            barrier.wait()
            row = _create(session, recipient_id, "concurrent")
            with lock:
                ids.append(row.id)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(ids) == 2
    assert len(set(ids)) == 1


@requires_db
def test_permanent_failure_never_reappears(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        row = _create(session, recipient_id)
    with SessionLocal.begin() as session:
        claim = NotificationOutboxRepository(session).claim_batch(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=1
        )[0]
        assert claim.claim_token is not None
        NotificationOutboxService(session).mark_delivery_failed(
            row.id,
            claim.claim_token,
            now=NOW,
            retryable=False,
            failure_code="RECIPIENT_UNDELIVERABLE",
        )
    with SessionLocal() as session:
        assert (
            NotificationOutboxRepository(session).list_eligible(
                now=NOW + timedelta(days=1), lease_expires_before=NOW, limit=100
            )
            == []
        )


@requires_db
@pytest.mark.parametrize("row_count", [1, 20, 100])
def test_pending_discovery_has_constant_query_count(recipient_id: UUID, row_count: int) -> None:
    with SessionLocal.begin() as session:
        for index in range(row_count):
            _create(session, recipient_id, f"queries-{row_count}-{index}")
    statements = 0

    def count_statement(*_args) -> None:
        nonlocal statements
        statements += 1

    with SessionLocal() as session:
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", count_statement)
        try:
            rows = NotificationOutboxRepository(session).list_eligible(
                now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=100
            )
        finally:
            event.remove(connection, "before_cursor_execute", count_statement)
        assert len(rows) == row_count
        assert statements == 1


@requires_db
@pytest.mark.parametrize("row_count", [1_000, 10_000, 50_000])
def test_mixed_discovery_plan_scales_with_bounded_index_work(
    recipient_id: UUID, row_count: int
) -> None:
    with SessionLocal.begin() as session:
        _seed_mixed_queue(session, recipient_id, row_count)
        session.execute(text("ANALYZE notification_outbox"))
    statement = NotificationOutboxRepository.eligible_statement(
        now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=20, lock=False
    )
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    with SessionLocal() as session:
        explained = session.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
        ).scalar_one()
        rows = list(session.scalars(statement))

    root = explained[0]["Plan"]
    nodes: list[dict] = []

    def visit(node: dict) -> None:
        nodes.append(node)
        for child in node.get("Plans", []):
            visit(child)

    visit(root)
    outbox_scans = [node for node in nodes if node.get("Relation Name") == "notification_outbox"]
    indexes = {node.get("Index Name") for node in outbox_scans if node.get("Index Name")}
    assert len(rows) == 20
    if row_count == 50_000:
        assert not any(node["Node Type"] == "Seq Scan" for node in outbox_scans)
        assert {
            "ix_notification_outbox_pending",
            "ix_notification_outbox_retry_due",
            "ix_notification_outbox_claim_expiry",
        }.issubset(indexes)
        assert all(
            node.get("Actual Rows", 0) <= 20 for node in outbox_scans if node.get("Index Name")
        )


@requires_db
@pytest.mark.parametrize("limit", [1, 20, 100])
def test_mixed_discovery_respects_limit(recipient_id: UUID, limit: int) -> None:
    with SessionLocal.begin() as session:
        _seed_mixed_queue(session, recipient_id, 1_000)
    with SessionLocal() as session:
        rows = NotificationOutboxRepository(session).list_eligible(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=limit
        )
        assert len(rows) == limit


@requires_db
def test_due_and_lease_boundaries_are_inclusive_and_fair(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        pending = _create(session, recipient_id, "fair-pending")
        pending.created_at = NOW - timedelta(minutes=3)
        retry = _create(session, recipient_id, "fair-retry")
        retry.delivery_state = NotificationDeliveryState.FAILED_RETRYABLE
        retry.next_attempt_at = NOW
        retry.created_at = NOW - timedelta(minutes=1)
        expired = _create(session, recipient_id, "fair-expired")
        expired.delivery_state = NotificationDeliveryState.CLAIMED
        expired.claim_token = uuid4()
        expired.claimed_at = NOW - timedelta(minutes=5)
        expired.created_at = NOW - timedelta(minutes=2)
    with SessionLocal() as session:
        rows = NotificationOutboxRepository(session).list_eligible(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=3
        )
        assert [row.id for row in rows] == [expired.id, pending.id, retry.id]


@requires_db
def test_equal_availability_order_is_stable_by_created_at_then_id(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        rows = [_create(session, recipient_id, f"stable-{index}") for index in range(3)]
        for row in rows:
            row.created_at = NOW
    expected = sorted(row.id for row in rows)
    with SessionLocal() as session:
        repository = NotificationOutboxRepository(session)
        first = repository.list_eligible(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=3
        )
        second = repository.list_eligible(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=3
        )
        assert [row.id for row in first] == expected
        assert [row.id for row in second] == expected


@requires_db
def test_concurrent_multirow_claims_are_disjoint(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        for index in range(12):
            _create(session, recipient_id, f"batch-{index}")
    barrier = threading.Barrier(2)
    batches: list[set[UUID]] = []
    lock = threading.Lock()

    def worker() -> None:
        with SessionLocal.begin() as session:
            barrier.wait()
            result = NotificationOutboxRepository(session).claim_batch(
                now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=6
            )
            with lock:
                batches.append({item.id for item in result})

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(batches) == 2
    assert len(batches[0]) == len(batches[1]) == 6
    assert batches[0].isdisjoint(batches[1])


@requires_db
def test_outbox_insert_failure_rolls_back_business_mutation(recipient_id: UUID) -> None:
    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as session:
            session.get_one(User, recipient_id).display_name = "Must not persist"
            _create(session, uuid4(), "invalid-recipient")
    with SessionLocal() as session:
        assert session.get_one(User, recipient_id).display_name != "Must not persist"


@requires_db
def test_oversize_failure_code_fails_without_transition(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        row = _create(session, recipient_id, "oversize")
    with SessionLocal.begin() as session:
        claimed = NotificationOutboxRepository(session).claim_batch(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=1
        )[0]
        token = claimed.claim_token
    assert token is not None
    with pytest.raises(DataError):
        with SessionLocal.begin() as session:
            NotificationOutboxService(session).mark_delivery_failed(
                row.id,
                token,
                now=NOW,
                retryable=False,
                failure_code="X" * 101,
            )
    with SessionLocal() as session:
        unchanged = session.get_one(NotificationOutbox, row.id)
        assert unchanged.delivery_state is NotificationDeliveryState.CLAIMED
        assert unchanged.claim_token == token


@requires_db
def test_read_only_discovery_does_not_touch_updated_at(recipient_id: UUID) -> None:
    with SessionLocal.begin() as session:
        row = _create(session, recipient_id, "read-only")
        row.updated_at = NOW - timedelta(days=1)
    with SessionLocal() as session:
        before = session.get_one(NotificationOutbox, row.id).updated_at
        NotificationOutboxRepository(session).list_eligible(
            now=NOW, lease_expires_before=NOW - timedelta(minutes=5), limit=1
        )
        session.expire_all()
        assert session.get_one(NotificationOutbox, row.id).updated_at == before
