"""Add the durable notification outbox foundation.

Revision ID: 20260828_0011
Revises: 20260827_0010
Create Date: 2026-08-28 00:11:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260828_0011"
down_revision: str | Sequence[str] | None = "20260827_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

delivery_state = postgresql.ENUM(
    "PENDING",
    "CLAIMED",
    "DELIVERED",
    "FAILED_RETRYABLE",
    "FAILED_PERMANENT",
    name="notification_delivery_state",
    create_type=False,
)


def upgrade() -> None:
    from alembic import op

    delivery_state.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_state", delivery_state, server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
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
            "attempt_count >= 0", name="ck_notification_outbox_attempt_non_negative"
        ),
        sa.CheckConstraint(
            "(delivery_state = 'CLAIMED' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL) "
            "OR (delivery_state <> 'CLAIMED' AND claim_token IS NULL AND claimed_at IS NULL)",
            name="ck_notification_outbox_claim_consistent",
        ),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_notification_outbox_dedupe_key"),
    )
    op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["created_at", "id"],
        postgresql_where=sa.text("delivery_state = 'PENDING'"),
    )
    op.create_index(
        "ix_notification_outbox_retry_due",
        "notification_outbox",
        ["next_attempt_at", "created_at", "id"],
        postgresql_where=sa.text("delivery_state = 'FAILED_RETRYABLE'"),
    )
    op.create_index(
        "ix_notification_outbox_claim_expiry",
        "notification_outbox",
        ["claimed_at", "created_at", "id"],
        postgresql_where=sa.text("delivery_state = 'CLAIMED'"),
    )
    op.create_index(
        "ix_notification_outbox_recipient",
        "notification_outbox",
        ["recipient_user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_notification_outbox_resource",
        "notification_outbox",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    from alembic import op

    op.drop_table("notification_outbox")
    delivery_state.drop(op.get_bind(), checkfirst=False)
