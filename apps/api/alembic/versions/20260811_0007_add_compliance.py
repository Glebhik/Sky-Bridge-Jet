"""Add the Phase 6 operator compliance & marketplace admission domain.

Adds operator admission, compliance evidence, operator/aircraft authorization, and
an append-only compliance audit trail. Existing operators receive no admission row
and are therefore not marketplace-admitted by default (no auto-approval).

Revision ID: 20260811_0007
Revises: 20260811_0006
Create Date: 2026-08-11 00:07:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0007"
down_revision: str | Sequence[str] | None = "20260811_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

operator_admission_status = postgresql.ENUM(
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "SUSPENDED",
    name="operator_admission_status",
    create_type=False,
)
aircraft_authorization_status = postgresql.ENUM(
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "SUSPENDED",
    name="aircraft_authorization_status",
    create_type=False,
)
evidence_status = postgresql.ENUM(
    "SUBMITTED",
    "UNDER_REVIEW",
    "VERIFIED",
    "REJECTED",
    "SUPERSEDED",
    name="evidence_status",
    create_type=False,
)
evidence_type = postgresql.ENUM(
    "OPERATING_AUTHORITY",
    "INSURANCE",
    "AIRCRAFT_OPERATING_AUTHORITY",
    "OTHER",
    name="evidence_type",
    create_type=False,
)
authority_basis = postgresql.ENUM(
    "OWNED",
    "LEASED",
    "MANAGED",
    "OPERATED_UNDER_AGREEMENT",
    "OTHER",
    name="authority_basis",
    create_type=False,
)
review_reason_code = postgresql.ENUM(
    "DOCUMENT_MISSING",
    "DOCUMENT_EXPIRED",
    "DOCUMENT_REJECTED",
    "AUTHORITY_NOT_VERIFIED",
    "INSURANCE_NOT_VERIFIED",
    "AIRCRAFT_AUTHORITY_NOT_VERIFIED",
    "INFORMATION_INCONSISTENT",
    "MANUAL_SUSPENSION",
    "OTHER",
    name="review_reason_code",
    create_type=False,
)
compliance_actor_type = postgresql.ENUM(
    "SYSTEM",
    "OPERATOR",
    "PLATFORM_REVIEWER",
    "PRODUCT_OWNER",
    name="compliance_actor_type",
    create_type=False,
)
compliance_entity_type = postgresql.ENUM(
    "OPERATOR_ADMISSION",
    "COMPLIANCE_EVIDENCE",
    "AIRCRAFT_AUTHORIZATION",
    name="compliance_entity_type",
    create_type=False,
)
compliance_action = postgresql.ENUM(
    "CREATED",
    "SUBMITTED",
    "REVIEW_STARTED",
    "APPROVED",
    "REJECTED",
    "SUSPENDED",
    "RESTORED",
    "VERIFIED",
    "SUPERSEDED",
    name="compliance_action",
    create_type=False,
)

_ALL_ENUMS = (
    operator_admission_status,
    aircraft_authorization_status,
    evidence_status,
    evidence_type,
    authority_basis,
    review_reason_code,
    compliance_actor_type,
    compliance_entity_type,
    compliance_action,
)


def upgrade() -> None:
    """Create the Phase 6 compliance schema (existing operators are not admitted)."""
    from alembic import op

    bind = op.get_bind()
    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "compliance_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", compliance_entity_type, nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", compliance_action, nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=True),
        sa.Column("new_status", sa.String(length=40), nullable=True),
        sa.Column("actor_type", compliance_actor_type, nullable=False),
        sa.Column("actor_reference", sa.String(length=200), nullable=True),
        sa.Column("reason_code", review_reason_code, nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_compliance_audit_events_entity",
        "compliance_audit_events",
        ["entity_type", "entity_id"],
    )

    op.create_table(
        "operator_admissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("status", operator_admission_status, nullable=False),
        sa.Column("reason_code", review_reason_code, nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operator_id", name="uq_operator_admissions_operator"),
    )

    op.create_table(
        "compliance_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("aircraft_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("status", evidence_status, nullable=False),
        sa.Column("authority_basis", authority_basis, nullable=True),
        sa.Column("reference_number", sa.String(length=200), nullable=True),
        sa.Column("issuing_authority", sa.String(length=200), nullable=True),
        sa.Column("jurisdiction", sa.String(length=2), nullable=True),
        sa.Column("insurer_name", sa.String(length=200), nullable=True),
        sa.Column("storage_object_reference", sa.String(length=500), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason_code", review_reason_code, nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effective_date IS NULL OR expiry_date IS NULL OR expiry_date >= effective_date",
            name="ck_compliance_evidence_validity_window",
        ),
        sa.ForeignKeyConstraint(
            ["aircraft_id", "operator_id"],
            ["aircraft.id", "aircraft.operator_id"],
            name="fk_compliance_evidence_aircraft_operator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["compliance_evidence.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compliance_evidence_operator_id", "compliance_evidence", ["operator_id"])
    op.create_index(
        "ix_compliance_evidence_operator_type",
        "compliance_evidence",
        ["operator_id", "evidence_type"],
    )

    op.create_table(
        "operator_aircraft_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("aircraft_id", sa.Uuid(), nullable=False),
        sa.Column("status", aircraft_authorization_status, nullable=False),
        sa.Column("authority_basis", authority_basis, nullable=False),
        sa.Column("reason_code", review_reason_code, nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["aircraft_id", "operator_id"],
            ["aircraft.id", "aircraft.operator_id"],
            name="fk_operator_aircraft_authorizations_aircraft_operator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_id", "aircraft_id", name="uq_operator_aircraft_authorizations_pair"
        ),
    )
    op.create_index(
        "ix_operator_aircraft_authorizations_operator_id",
        "operator_aircraft_authorizations",
        ["operator_id"],
    )


def downgrade() -> None:
    """Remove the Phase 6 compliance schema and its enum types."""
    from alembic import op

    op.drop_index(
        "ix_operator_aircraft_authorizations_operator_id",
        table_name="operator_aircraft_authorizations",
    )
    op.drop_table("operator_aircraft_authorizations")
    op.drop_index("ix_compliance_evidence_operator_type", table_name="compliance_evidence")
    op.drop_index("ix_compliance_evidence_operator_id", table_name="compliance_evidence")
    op.drop_table("compliance_evidence")
    op.drop_table("operator_admissions")
    op.drop_index("ix_compliance_audit_events_entity", table_name="compliance_audit_events")
    op.drop_table("compliance_audit_events")

    bind = op.get_bind()
    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
