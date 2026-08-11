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
from sqlalchemy.orm import Mapped, mapped_column

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.bookings.domain import (
    BookingStatus,
    CancellationActor,
    CancellationReason,
    RejectionReason,
)

_ACTIVE_BOOKING_PREDICATE = "status IN ('PENDING_OPERATOR_CONFIRMATION', 'CONFIRMED')"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Booking(Base):
    """The booking workflow resulting from one selected operator offer.

    The Booking preserves an immutable commercial snapshot of the selected offer
    so historical truth survives later reference-data changes. Monetary amounts
    are integer minor units (ADR-013). The Booking, not the TripRequest, is the
    authoritative source of booking state.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        # The booking's offer, trip, operator, and aircraft must all agree, via a
        # single composite foreign key into the offer's composite unique key.
        ForeignKeyConstraint(
            ["operator_offer_id", "trip_request_id", "operator_id", "aircraft_id"],
            [
                "operator_offers.id",
                "operator_offers.trip_request_id",
                "operator_offers.operator_id",
                "operator_offers.aircraft_id",
            ],
            ondelete="RESTRICT",
            name="fk_bookings_offer_consistency",
        ),
        CheckConstraint("operator_amount_minor >= 0", name="ck_bookings_operator_amount_non_neg"),
        CheckConstraint("platform_fee_minor >= 0", name="ck_bookings_platform_fee_non_neg"),
        CheckConstraint("tax_amount_minor >= 0", name="ck_bookings_tax_non_neg"),
        CheckConstraint("total_amount_minor >= 0", name="ck_bookings_total_non_neg"),
        CheckConstraint(
            "total_amount_minor = operator_amount_minor + platform_fee_minor + tax_amount_minor",
            name="ck_bookings_total_consistent",
        ),
        CheckConstraint("currency IN ('EUR', 'GBP', 'USD')", name="ck_bookings_currency_supported"),
        UniqueConstraint("reference", name="uq_bookings_reference"),
        # At most one active booking workflow per trip request. Rejected and
        # cancelled bookings remain as history and do not block a new workflow.
        Index(
            "uq_bookings_one_active_per_trip",
            "trip_request_id",
            unique=True,
            postgresql_where=_ACTIVE_BOOKING_PREDICATE,
        ),
        Index("ix_bookings_trip_request_id", "trip_request_id"),
        Index("ix_bookings_operator_offer_id", "operator_offer_id"),
        Index("ix_bookings_operator_id", "operator_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(32), nullable=False)

    trip_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("trip_requests.id", ondelete="RESTRICT"), nullable=False
    )
    operator_offer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aircraft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        default=BookingStatus.PENDING_OPERATOR_CONFIRMATION,
        nullable=False,
    )

    # Immutable commercial snapshot copied from the selected offer.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    operator_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offer_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    operator_legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    aircraft_registration: Mapped[str] = mapped_column(String(20), nullable=False)
    aircraft_manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    aircraft_model: Mapped[str] = mapped_column(String(100), nullable=False)
    aircraft_category: Mapped[str] = mapped_column(String(32), nullable=False)

    # Operator confirmation metadata.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_confirmation_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Operator rejection metadata.
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[RejectionReason | None] = mapped_column(
        Enum(RejectionReason, name="booking_rejection_reason"), nullable=True
    )
    rejection_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Cancellation metadata (workflow state only; no financial settlement).
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_actor: Mapped[CancellationActor | None] = mapped_column(
        Enum(CancellationActor, name="booking_cancellation_actor"), nullable=True
    )
    cancellation_reason: Mapped[CancellationReason | None] = mapped_column(
        Enum(CancellationReason, name="booking_cancellation_reason"), nullable=True
    )
    cancellation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
