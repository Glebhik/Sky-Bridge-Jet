from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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
from sky_bridge_jet.modules.compliance.domain import (
    ActorType,
    AircraftAuthorizationStatus,
    AuthorityBasis,
    ComplianceAction,
    ComplianceEntityType,
    EvidenceStatus,
    EvidenceType,
    OperatorAdmissionStatus,
    ReviewReasonCode,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# Shared enum instances for types referenced by more than one table, so DDL emits
# each PostgreSQL type exactly once.
_REVIEW_REASON_ENUM = Enum(ReviewReasonCode, name="review_reason_code")
_AUTHORITY_BASIS_ENUM = Enum(AuthorityBasis, name="authority_basis")


class OperatorAdmission(Base):
    """One marketplace-admission record per operator with its review lifecycle.

    Existing operators have no admission row and are therefore not admitted; a
    newly created admission starts as DRAFT. Admission is never inherited or
    auto-approved.
    """

    __tablename__ = "operator_admissions"
    __table_args__ = (UniqueConstraint("operator_id", name="uq_operator_admissions_operator"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[OperatorAdmissionStatus] = mapped_column(
        Enum(OperatorAdmissionStatus, name="operator_admission_status"),
        default=OperatorAdmissionStatus.DRAFT,
        nullable=False,
    )
    reason_code: Mapped[ReviewReasonCode | None] = mapped_column(_REVIEW_REASON_ENUM, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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


class ComplianceEvidence(Base):
    """Structured compliance evidence (authority/AOC, insurance, aircraft authority).

    The database stores metadata and an opaque storage object reference, never raw
    document contents. Expiration is derived from ``expiry_date`` during eligibility
    evaluation, not persisted.
    """

    __tablename__ = "compliance_evidence"
    __table_args__ = (
        # When aircraft-scoped, the aircraft must belong to the same operator.
        ForeignKeyConstraint(
            ["aircraft_id", "operator_id"],
            ["aircraft.id", "aircraft.operator_id"],
            ondelete="RESTRICT",
            name="fk_compliance_evidence_aircraft_operator",
        ),
        CheckConstraint(
            "effective_date IS NULL OR expiry_date IS NULL OR expiry_date >= effective_date",
            name="ck_compliance_evidence_validity_window",
        ),
        Index("ix_compliance_evidence_operator_id", "operator_id"),
        Index("ix_compliance_evidence_operator_type", "operator_id", "evidence_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    aircraft_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, name="evidence_type"), nullable=False
    )
    status: Mapped[EvidenceStatus] = mapped_column(
        Enum(EvidenceStatus, name="evidence_status"),
        default=EvidenceStatus.SUBMITTED,
        nullable=False,
    )
    authority_basis: Mapped[AuthorityBasis | None] = mapped_column(
        _AUTHORITY_BASIS_ENUM, nullable=True
    )
    reference_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issuing_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(2), nullable=True)
    insurer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    storage_object_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_reason_code: Mapped[ReviewReasonCode | None] = mapped_column(
        _REVIEW_REASON_ENUM, nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("compliance_evidence.id", ondelete="RESTRICT"), nullable=True
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


class OperatorAircraftAuthorization(Base):
    """Marketplace authorization for one operator/aircraft combination.

    Approval is explicit and never inherited from operator admission. The
    composite foreign key enforces that the aircraft belongs to the operator.
    """

    __tablename__ = "operator_aircraft_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "aircraft_id", name="uq_operator_aircraft_authorizations_pair"
        ),
        ForeignKeyConstraint(
            ["aircraft_id", "operator_id"],
            ["aircraft.id", "aircraft.operator_id"],
            ondelete="RESTRICT",
            name="fk_operator_aircraft_authorizations_aircraft_operator",
        ),
        Index("ix_operator_aircraft_authorizations_operator_id", "operator_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    aircraft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[AircraftAuthorizationStatus] = mapped_column(
        Enum(AircraftAuthorizationStatus, name="aircraft_authorization_status"),
        default=AircraftAuthorizationStatus.DRAFT,
        nullable=False,
    )
    authority_basis: Mapped[AuthorityBasis] = mapped_column(_AUTHORITY_BASIS_ENUM, nullable=False)
    reason_code: Mapped[ReviewReasonCode | None] = mapped_column(_REVIEW_REASON_ENUM, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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


class ComplianceAuditEvent(Base):
    """Append-only audit record of a material compliance decision.

    Written only by inserts; the service never updates or deletes audit rows.
    Stores no secrets and no raw document contents.
    """

    __tablename__ = "compliance_audit_events"
    __table_args__ = (Index("ix_compliance_audit_events_entity", "entity_type", "entity_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    entity_type: Mapped[ComplianceEntityType] = mapped_column(
        Enum(ComplianceEntityType, name="compliance_entity_type"), nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[ComplianceAction] = mapped_column(
        Enum(ComplianceAction, name="compliance_action"), nullable=False
    )
    previous_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="compliance_actor_type"), nullable=False
    )
    actor_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason_code: Mapped[ReviewReasonCode | None] = mapped_column(_REVIEW_REASON_ENUM, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
