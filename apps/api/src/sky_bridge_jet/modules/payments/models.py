from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.payments.domain import (
    PaymentOperationResult,
    PaymentOperationType,
    PaymentStatus,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Payment(Base):
    """The single payment obligation for one booking.

    Amounts are integer minor units (ADR-013). The commercial snapshot is bound
    to the booking's amounts by a composite foreign key so it can never diverge.
    No card/bank credentials are ever stored — only provider-neutral references.
    """

    __tablename__ = "payments"
    __table_args__ = (
        # Exactly one payment per booking, whose commercial snapshot must equal
        # the booking's commercial amounts.
        ForeignKeyConstraint(
            [
                "booking_id",
                "currency",
                "operator_amount_minor",
                "platform_fee_minor",
                "tax_amount_minor",
                "total_amount_minor",
            ],
            [
                "bookings.id",
                "bookings.currency",
                "bookings.operator_amount_minor",
                "bookings.platform_fee_minor",
                "bookings.tax_amount_minor",
                "bookings.total_amount_minor",
            ],
            ondelete="RESTRICT",
            name="fk_payments_booking_snapshot",
        ),
        UniqueConstraint("booking_id", name="uq_payments_booking"),
        UniqueConstraint("reference", name="uq_payments_reference"),
        CheckConstraint("operator_amount_minor >= 0", name="ck_payments_operator_amount_non_neg"),
        CheckConstraint("platform_fee_minor >= 0", name="ck_payments_platform_fee_non_neg"),
        CheckConstraint("tax_amount_minor >= 0", name="ck_payments_tax_non_neg"),
        CheckConstraint("total_amount_minor >= 0", name="ck_payments_total_non_neg"),
        CheckConstraint(
            "total_amount_minor = operator_amount_minor + platform_fee_minor + tax_amount_minor",
            name="ck_payments_total_consistent",
        ),
        CheckConstraint("currency IN ('EUR', 'GBP', 'USD')", name="ck_payments_currency_supported"),
        CheckConstraint(
            "authorized_amount_minor IS NULL OR authorized_amount_minor >= 0",
            name="ck_payments_authorized_non_neg",
        ),
        CheckConstraint("captured_amount_minor >= 0", name="ck_payments_captured_non_neg"),
        CheckConstraint("refunded_amount_minor >= 0", name="ck_payments_refunded_non_neg"),
        # Captured can never exceed authorized; refunded can never exceed captured.
        CheckConstraint(
            "authorized_amount_minor IS NULL OR captured_amount_minor <= authorized_amount_minor",
            name="ck_payments_captured_le_authorized",
        ),
        CheckConstraint(
            "refunded_amount_minor <= captured_amount_minor",
            name="ck_payments_refunded_le_captured",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    booking_id: Mapped[UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.CREATED,
        nullable=False,
    )

    # Immutable commercial snapshot (bound to the booking by composite FK).
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    operator_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Running financial totals.
    authorized_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    captured_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    refunded_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Provider-neutral references (identifiers, never secrets/credentials).
    provider_payment_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    operations: Mapped[list[PaymentOperation]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", passive_deletes=True
    )

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


class PaymentOperation(Base):
    """An idempotent financial command against a payment (authorize/capture/void/refund).

    The unique idempotency key makes retries and concurrent duplicates safe. This
    table doubles as the payment attempt/audit ledger; refund operations are the
    refund history.
    """

    __tablename__ = "payment_operations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_operations_idempotency_key"),
        CheckConstraint("amount_minor >= 0", name="ck_payment_operations_amount_non_neg"),
        Index("ix_payment_operations_payment_id", "payment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[PaymentOperationType] = mapped_column(
        Enum(PaymentOperationType, name="payment_operation_type"), nullable=False
    )
    result: Mapped[PaymentOperationResult] = mapped_column(
        Enum(PaymentOperationResult, name="payment_operation_result"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    payment: Mapped[Payment] = relationship(back_populates="operations")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
