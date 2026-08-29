"""Add controlled-pilot participation and governance state.

Revision ID: 20260830_0013
Revises: 20260829_0012
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0013"
down_revision: str | Sequence[str] | None = "20260829_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()
    participant_type = postgresql.ENUM(
        "CUSTOMER", "OPERATOR", name="pilot_participant_type", create_type=False
    )
    participant_status = postgresql.ENUM(
        "INVITED",
        "ACTIVE",
        "SUSPENDED",
        "REVOKED",
        name="pilot_participant_status",
        create_type=False,
    )
    pilot_mode = postgresql.ENUM(
        "INTERNAL_ONLY",
        "CONTROLLED_EXTERNAL",
        "PAUSED",
        name="pilot_mode",
        create_type=False,
    )
    reason = postgresql.ENUM(
        "PILOT_INVITATION",
        "OWNER_APPROVED",
        "MANUAL_REVIEW_REQUIRED",
        "COMPLIANCE_CONCERN",
        "SECURITY_OR_PRIVACY_CONCERN",
        "PAYMENT_AMBIGUITY",
        "OPERATIONAL_PAUSE",
        "ACCESS_NO_LONGER_REQUIRED",
        name="pilot_reason",
        create_type=False,
    )
    for enum in (participant_type, participant_status, pilot_mode, reason):
        enum.create(bind, checkfirst=False)
    op.create_table(
        "pilot_governance_state",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mode", pilot_mode, nullable=False),
        sa.Column(
            "payment_initiation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "pilot_participants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("participant_type", participant_type, nullable=False),
        sa.Column("status", participant_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_pilot_participants_created_id", "pilot_participants", ["created_at", "id"])
    op.create_index(
        "ix_pilot_participants_status_created", "pilot_participants", ["status", "created_at", "id"]
    )
    op.create_index(
        "ix_pilot_participants_type_status",
        "pilot_participants",
        ["participant_type", "status", "id"],
    )
    op.create_table(
        "pilot_governance_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_state", sa.String(32), nullable=False),
        sa.Column("new_state", sa.String(32), nullable=False),
        sa.Column("reason", reason, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_id"], ["pilot_participants.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_pilot_audits_created", "pilot_governance_audits", ["created_at", "id"])
    op.execute(
        sa.insert(
            sa.table(
                "pilot_governance_state",
                sa.column("id", sa.Uuid()),
                sa.column("mode", pilot_mode),
                sa.column("payment_initiation_enabled", sa.Boolean()),
                sa.column("version", sa.Integer()),
            )
        ).values(
            id=UUID("00000000-0000-0000-0000-00000000010b"),
            mode="INTERNAL_ONLY",
            payment_initiation_enabled=False,
            version=1,
        )
    )


def downgrade() -> None:
    from alembic import op

    op.drop_table("pilot_governance_audits")
    op.drop_table("pilot_participants")
    op.drop_table("pilot_governance_state")
    bind = op.get_bind()
    for name in (
        "pilot_reason",
        "pilot_mode",
        "pilot_participant_status",
        "pilot_participant_type",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
