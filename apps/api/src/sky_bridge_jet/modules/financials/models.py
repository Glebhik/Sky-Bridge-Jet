from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.financials.domain import OnboardingStatus, WebhookProcessingStatus
from sky_bridge_jet.modules.payments.models import payment_provider_enum


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OperatorConnectedAccount(Base):
    """The PSP connected-account mapping for one operator, per provider.

    Records provider capability state translated into a stable domain status. It
    stores only provider-neutral identifiers — never bank data, identity
    documents, or beneficial-owner information. This is financial onboarding,
    separate from Phase 6 aviation marketplace admission.
    """

    __tablename__ = "operator_connected_accounts"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "payment_provider", name="uq_operator_connected_accounts_operator"
        ),
        UniqueConstraint(
            "provider_account_reference", name="uq_operator_connected_accounts_reference"
        ),
        Index("ix_operator_connected_accounts_operator_id", "operator_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    payment_provider: Mapped[str] = mapped_column(payment_provider_enum, nullable=False)
    provider_account_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    onboarding_status: Mapped[OnboardingStatus] = mapped_column(
        Enum(OnboardingStatus, name="financial_onboarding_status"),
        default=OnboardingStatus.NOT_STARTED,
        nullable=False,
    )
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requirements_due: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    account_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
    synchronized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        server_default=func.now(),
        onupdate=_utc_now,
        nullable=False,
    )


class ProviderWebhookEvent(Base):
    """Idempotent record of a received provider webhook event (data-minimized).

    A unique (provider, provider_event_id) makes duplicate deliveries safe. The
    raw event body is not persisted; only normalized metadata is kept.
    """

    __tablename__ = "provider_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "payment_provider", "provider_event_id", name="uq_provider_webhook_events_event"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_provider: Mapped[str] = mapped_column(payment_provider_enum, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[WebhookProcessingStatus] = mapped_column(
        Enum(WebhookProcessingStatus, name="webhook_processing_status"),
        default=WebhookProcessingStatus.RECEIVED,
        nullable=False,
    )
    entity_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(120), nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
