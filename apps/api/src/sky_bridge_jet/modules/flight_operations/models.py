from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.flight_operations.domain import FlightOperationStatus


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FlightOperation(Base):
    """One durable operational handoff linked to one commercial Booking."""

    __tablename__ = "flight_operations"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_flight_operations_booking"),
        Index("ix_flight_operations_created", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    booking_id: Mapped[UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[FlightOperationStatus] = mapped_column(
        Enum(FlightOperationStatus, name="flight_operation_status"),
        default=FlightOperationStatus.HANDOFF_CREATED,
        nullable=False,
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
