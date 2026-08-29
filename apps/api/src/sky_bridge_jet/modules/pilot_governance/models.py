from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.pilot_governance.domain import (
    PilotMode,
    PilotParticipantStatus,
    PilotParticipantType,
    PilotReason,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


PILOT_GOVERNANCE_SINGLETON_ID = UUID("00000000-0000-0000-0000-00000000010b")


class PilotGovernanceState(Base):
    __tablename__ = "pilot_governance_state"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    mode: Mapped[PilotMode] = mapped_column(Enum(PilotMode, name="pilot_mode"), nullable=False)
    payment_initiation_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )


class PilotParticipant(Base):
    __tablename__ = "pilot_participants"
    __table_args__ = (
        Index("ix_pilot_participants_created_id", "created_at", "id"),
        Index("ix_pilot_participants_status_created", "status", "created_at", "id"),
        Index("ix_pilot_participants_type_status", "participant_type", "status", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    participant_type: Mapped[PilotParticipantType] = mapped_column(
        Enum(PilotParticipantType, name="pilot_participant_type"), nullable=False
    )
    status: Mapped[PilotParticipantStatus] = mapped_column(
        Enum(PilotParticipantStatus, name="pilot_participant_status"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )


class PilotGovernanceAudit(Base):
    __tablename__ = "pilot_governance_audits"
    __table_args__ = (Index("ix_pilot_audits_created", "created_at", "id"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pilot_participants.id", ondelete="RESTRICT"), nullable=True
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_state: Mapped[str] = mapped_column(String(32), nullable=False)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[PilotReason] = mapped_column(
        Enum(PilotReason, name="pilot_reason"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
