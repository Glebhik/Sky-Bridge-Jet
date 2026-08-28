from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.notifications.domain import (
    NotificationClaimConflictError,
    NotificationDedupeConflictError,
    NotificationDeliveryState,
)
from sky_bridge_jet.modules.notifications.models import NotificationOutbox
from sky_bridge_jet.modules.notifications.repositories import NotificationOutboxRepository


class NotificationOutboxService:
    """Transaction-neutral primitives for trusted server-side callers."""

    def __init__(self, session: Session) -> None:
        self.repository = NotificationOutboxRepository(session)

    def create_intent(
        self,
        *,
        dedupe_key: str,
        event_type: str,
        recipient_user_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> NotificationOutbox:
        notification = self.repository.create_or_get(
            dedupe_key=dedupe_key,
            event_type=event_type,
            recipient_user_id=recipient_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if (
            notification.event_type != event_type
            or notification.recipient_user_id != recipient_user_id
            or notification.resource_type != resource_type
            or notification.resource_id != resource_id
        ):
            raise NotificationDedupeConflictError(
                "Notification dedupe identity conflicts with existing trusted facts"
            )
        return notification

    def mark_delivered(
        self, notification_id: UUID, claim_token: UUID, *, now: datetime
    ) -> NotificationOutbox:
        return self._transition(
            notification_id,
            claim_token,
            state=NotificationDeliveryState.DELIVERED,
            now=now,
            next_attempt_at=None,
            failure_code=None,
        )

    def mark_delivery_failed(
        self,
        notification_id: UUID,
        claim_token: UUID,
        *,
        now: datetime,
        retryable: bool,
        failure_code: str,
        next_attempt_at: datetime | None = None,
    ) -> NotificationOutbox:
        if retryable and next_attempt_at is None:
            raise ValueError("retryable failure requires next_attempt_at")
        return self._transition(
            notification_id,
            claim_token,
            state=(
                NotificationDeliveryState.FAILED_RETRYABLE
                if retryable
                else NotificationDeliveryState.FAILED_PERMANENT
            ),
            now=now,
            next_attempt_at=next_attempt_at if retryable else None,
            failure_code=failure_code,
        )

    def _transition(
        self,
        notification_id: UUID,
        claim_token: UUID,
        *,
        state: NotificationDeliveryState,
        now: datetime,
        next_attempt_at: datetime | None,
        failure_code: str | None,
    ) -> NotificationOutbox:
        notification = self.repository.transition_claim(
            notification_id,
            claim_token,
            state=state,
            now=now,
            next_attempt_at=next_attempt_at,
            failure_code=failure_code,
        )
        if notification is None:
            raise NotificationClaimConflictError("Notification claim is no longer authoritative")
        return notification
