from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.notifications.domain import NotificationDeliveryState


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationOutbox(Base):
    """One durable, deduplicated notification intent; never an arbitrary message payload."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_notification_outbox_attempt_non_negative"),
        CheckConstraint(
            "(delivery_state = 'CLAIMED' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL) "
            "OR (delivery_state <> 'CLAIMED' AND claim_token IS NULL AND claimed_at IS NULL)",
            name="ck_notification_outbox_claim_consistent",
        ),
        Index(
            "ix_notification_outbox_pending",
            "created_at",
            "id",
            postgresql_where=text("delivery_state = 'PENDING'"),
        ),
        Index(
            "ix_notification_outbox_retry_due",
            "next_attempt_at",
            "created_at",
            "id",
            postgresql_where=text("delivery_state = 'FAILED_RETRYABLE'"),
        ),
        Index(
            "ix_notification_outbox_claim_expiry",
            "claimed_at",
            "created_at",
            "id",
            postgresql_where=text("delivery_state = 'CLAIMED'"),
        ),
        Index("ix_notification_outbox_recipient", "recipient_user_id", "created_at", "id"),
        Index("ix_notification_outbox_resource", "resource_type", "resource_id"),
        Index(
            "uq_notification_outbox_provider_message",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    delivery_state: Mapped[NotificationDeliveryState] = mapped_column(
        Enum(NotificationDeliveryState, name="notification_delivery_state"),
        default=NotificationDeliveryState.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_delivery_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        server_default=func.now(),
        onupdate=_utc_now,
        nullable=False,
    )


class NotificationProviderEvent(Base):
    """Minimal idempotency ledger for verified provider delivery facts."""

    __tablename__ = "notification_provider_events"
    __table_args__ = (
        Index(
            "ix_notification_provider_events_message",
            "provider_message_id",
            "occurred_at",
            "event_type",
            "provider_event_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
