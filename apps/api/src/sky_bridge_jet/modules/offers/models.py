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
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.offers.domain import OfferStatus

_SELECTED_PREDICATE = "status = 'SELECTED'"
_ACTIVE_OFFER_PREDICATE = "status IN ('DRAFT', 'SUBMITTED', 'SELECTED')"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OperatorOffer(Base):
    """A commercial offer from one operator, for one aircraft, on one trip request.

    Monetary amounts are stored as integer minor units (for example euro cents)
    to avoid floating point. Operator and aircraft identity are snapshotted so the
    offer remains historically meaningful if that reference data changes later.
    """

    __tablename__ = "operator_offers"
    __table_args__ = (
        # An offered aircraft must belong to the offering operator.
        ForeignKeyConstraint(
            ["aircraft_id", "operator_id"],
            ["aircraft.id", "aircraft.operator_id"],
            ondelete="RESTRICT",
            name="fk_operator_offers_aircraft_operator",
        ),
        CheckConstraint(
            "operator_amount_minor >= 0",
            name="ck_operator_offers_operator_amount_non_negative",
        ),
        CheckConstraint(
            "platform_fee_minor >= 0", name="ck_operator_offers_platform_fee_non_negative"
        ),
        CheckConstraint("tax_amount_minor >= 0", name="ck_operator_offers_tax_non_negative"),
        CheckConstraint("total_amount_minor >= 0", name="ck_operator_offers_total_non_negative"),
        CheckConstraint(
            "total_amount_minor = operator_amount_minor + platform_fee_minor + tax_amount_minor",
            name="ck_operator_offers_total_consistent",
        ),
        CheckConstraint(
            "currency IN ('EUR', 'GBP', 'USD')", name="ck_operator_offers_currency_supported"
        ),
        # Composite unique target so a booking's composite foreign key can enforce
        # that its offer, trip, operator, and aircraft all agree (Phase 4).
        UniqueConstraint(
            "id",
            "trip_request_id",
            "operator_id",
            "aircraft_id",
            name="uq_operator_offers_booking_ref",
        ),
        # At most one selected offer per trip request (single-selection invariant).
        Index(
            "uq_operator_offers_one_selected_per_trip",
            "trip_request_id",
            unique=True,
            postgresql_where=_SELECTED_PREDICATE,
        ),
        # Prevent accidental duplicate active offers for the same aircraft on a
        # trip; a withdrawn offer frees the slot for a genuine replacement.
        Index(
            "uq_operator_offers_active_aircraft",
            "trip_request_id",
            "operator_id",
            "aircraft_id",
            unique=True,
            postgresql_where=_ACTIVE_OFFER_PREDICATE,
        ),
        Index("ix_operator_offers_trip_request_id", "trip_request_id"),
        Index("ix_operator_offers_operator_id", "operator_id"),
        Index("ix_operator_offers_aircraft_id", "aircraft_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trip_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("trip_requests.id", ondelete="RESTRICT"), nullable=False
    )
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    # Referential integrity for aircraft_id is carried by the composite foreign
    # key in __table_args__, which additionally enforces operator ownership.
    aircraft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[OfferStatus] = mapped_column(
        Enum(OfferStatus, name="offer_status"), default=OfferStatus.DRAFT, nullable=False
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    operator_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Snapshotted operator and aircraft identity for historical integrity.
    operator_legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    aircraft_registration: Mapped[str] = mapped_column(String(20), nullable=False)
    aircraft_manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    aircraft_model: Mapped[str] = mapped_column(String(100), nullable=False)
    aircraft_category: Mapped[str] = mapped_column(String(32), nullable=False)

    # Limited, deliberately non-legal commercial terms.
    operator_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancellation_policy: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    included_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_services: Mapped[str | None] = mapped_column(Text, nullable=True)

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
