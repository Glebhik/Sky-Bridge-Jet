from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CompoundSelect

from sky_bridge_jet.modules.notifications.domain import NotificationDeliveryState
from sky_bridge_jet.modules.notifications.models import NotificationOutbox

MAX_CLAIM_BATCH = 100


class NotificationOutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_or_get(
        self,
        *,
        dedupe_key: str,
        event_type: str,
        recipient_user_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> NotificationOutbox:
        statement = (
            insert(NotificationOutbox)
            .values(
                id=uuid4(),
                dedupe_key=dedupe_key,
                event_type=event_type,
                recipient_user_id=recipient_user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                delivery_state=NotificationDeliveryState.PENDING,
                attempt_count=0,
            )
            .on_conflict_do_nothing(index_elements=[NotificationOutbox.dedupe_key])
            .returning(NotificationOutbox.id)
        )
        created_id = self.session.scalar(statement)
        if created_id is not None:
            return self.session.get_one(NotificationOutbox, created_id)
        existing = self.session.scalar(
            select(NotificationOutbox).where(NotificationOutbox.dedupe_key == dedupe_key)
        )
        if existing is None:  # defensive: ON CONFLICT guarantees a row
            raise RuntimeError("Notification dedupe convergence failed")
        return existing

    @staticmethod
    def _bounded_candidates(
        now: datetime, lease_expires_before: datetime, limit: int, *, lock: bool
    ) -> CompoundSelect[tuple[UUID, datetime | None]]:
        pending = (
            select(
                NotificationOutbox.id.label("id"),
                NotificationOutbox.created_at.label("available_at"),
            )
            .where(NotificationOutbox.delivery_state == NotificationDeliveryState.PENDING)
            .order_by(NotificationOutbox.created_at.asc(), NotificationOutbox.id.asc())
            .limit(limit)
        )
        retryable = (
            select(
                NotificationOutbox.id.label("id"),
                NotificationOutbox.next_attempt_at.label("available_at"),
            )
            .where(
                NotificationOutbox.delivery_state == NotificationDeliveryState.FAILED_RETRYABLE,
                NotificationOutbox.next_attempt_at <= now,
            )
            .order_by(
                NotificationOutbox.next_attempt_at.asc(),
                NotificationOutbox.created_at.asc(),
                NotificationOutbox.id.asc(),
            )
            .limit(limit)
        )
        expired_claim = (
            select(
                NotificationOutbox.id.label("id"),
                NotificationOutbox.claimed_at.label("available_at"),
            )
            .where(
                NotificationOutbox.delivery_state == NotificationDeliveryState.CLAIMED,
                NotificationOutbox.claimed_at <= lease_expires_before,
            )
            .order_by(
                NotificationOutbox.claimed_at.asc(),
                NotificationOutbox.created_at.asc(),
                NotificationOutbox.id.asc(),
            )
            .limit(limit)
        )
        if lock:
            pending_cte = pending.with_for_update(of=NotificationOutbox, skip_locked=True).cte(
                "locked_pending_notifications"
            )
            retryable_cte = retryable.with_for_update(of=NotificationOutbox, skip_locked=True).cte(
                "locked_retryable_notifications"
            )
            expired_claim_cte = expired_claim.with_for_update(
                of=NotificationOutbox, skip_locked=True
            ).cte("locked_expired_claim_notifications")
            return union_all(
                select(pending_cte.c.id, pending_cte.c.available_at),
                select(retryable_cte.c.id, retryable_cte.c.available_at),
                select(expired_claim_cte.c.id, expired_claim_cte.c.available_at),
            )
        return union_all(pending, retryable, expired_claim)

    @classmethod
    def eligible_statement(
        cls, *, now: datetime, lease_expires_before: datetime, limit: int, lock: bool
    ) -> Select[tuple[NotificationOutbox]]:
        candidates = cls._bounded_candidates(now, lease_expires_before, limit, lock=lock).cte(
            "bounded_notification_candidates"
        )
        statement = (
            select(NotificationOutbox)
            .join(candidates, candidates.c.id == NotificationOutbox.id)
            .order_by(
                candidates.c.available_at.asc(),
                NotificationOutbox.created_at.asc(),
                NotificationOutbox.id.asc(),
            )
            .limit(limit)
        )
        return statement

    def list_eligible(
        self, *, now: datetime, lease_expires_before: datetime, limit: int
    ) -> list[NotificationOutbox]:
        self._validate_limit(limit)
        statement = self.eligible_statement(
            now=now, lease_expires_before=lease_expires_before, limit=limit, lock=False
        )
        return list(self.session.scalars(statement))

    def claim_batch(
        self, *, now: datetime, lease_expires_before: datetime, limit: int
    ) -> list[NotificationOutbox]:
        self._validate_limit(limit)
        candidates = self.eligible_statement(
            now=now, lease_expires_before=lease_expires_before, limit=limit, lock=True
        ).with_only_columns(NotificationOutbox.id)
        statement = (
            update(NotificationOutbox)
            .where(NotificationOutbox.id.in_(candidates))
            .values(
                delivery_state=NotificationDeliveryState.CLAIMED,
                claim_token=uuid4(),
                claimed_at=now,
                last_attempt_at=now,
                attempt_count=NotificationOutbox.attempt_count + 1,
                failure_code=None,
                updated_at=now,
            )
            .returning(NotificationOutbox)
        )
        claimed = list(
            self.session.scalars(statement, execution_options={"synchronize_session": False})
        )
        claimed.sort(key=self._effective_order)
        return claimed

    @staticmethod
    def _effective_order(notification: NotificationOutbox) -> tuple[datetime, datetime, UUID]:
        if notification.delivery_state is NotificationDeliveryState.CLAIMED:
            # A freshly claimed row retains the source class timestamps. Retry rows have
            # next_attempt_at; recovered claims have claimed_at overwritten, so their
            # original last_attempt_at is the closest factual availability tie-breaker.
            available_at = (
                notification.next_attempt_at
                or notification.last_attempt_at
                or notification.created_at
            )
        else:
            available_at = notification.created_at
        return available_at, notification.created_at, notification.id

    def transition_claim(
        self,
        notification_id: UUID,
        claim_token: UUID,
        *,
        state: NotificationDeliveryState,
        now: datetime,
        next_attempt_at: datetime | None,
        failure_code: str | None,
    ) -> NotificationOutbox | None:
        statement = (
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == notification_id,
                NotificationOutbox.delivery_state == NotificationDeliveryState.CLAIMED,
                NotificationOutbox.claim_token == claim_token,
            )
            .values(
                delivery_state=state,
                claim_token=None,
                claimed_at=None,
                next_attempt_at=next_attempt_at,
                delivered_at=now if state is NotificationDeliveryState.DELIVERED else None,
                failure_code=failure_code,
                updated_at=now,
            )
            .returning(NotificationOutbox)
        )
        return self.session.scalar(statement, execution_options={"synchronize_session": False})

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit < 1 or limit > MAX_CLAIM_BATCH:
            raise ValueError(f"limit must be between 1 and {MAX_CLAIM_BATCH}")
