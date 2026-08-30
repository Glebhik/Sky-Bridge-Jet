"""Add bounded provider delivery facts for marketplace notification operations.

Revision ID: 20260901_0015
Revises: 20260831_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "20260901_0015"
down_revision: str | Sequence[str] | None = "20260831_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.add_column("notification_outbox", sa.Column("provider_message_id", sa.String(255)))
    op.add_column("notification_outbox", sa.Column("provider_delivery_state", sa.String(40)))
    op.add_column("notification_outbox", sa.Column("provider_event_at", sa.DateTime(timezone=True)))
    op.create_index(
        "uq_notification_outbox_provider_message",
        "notification_outbox",
        ["provider_message_id"],
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )
    op.create_table(
        "notification_provider_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_notification_provider_events_message",
        "notification_provider_events",
        ["provider_message_id", "occurred_at", "event_type", "provider_event_id"],
    )


def downgrade() -> None:
    from alembic import op

    op.drop_table("notification_provider_events")
    op.drop_index("uq_notification_outbox_provider_message", table_name="notification_outbox")
    op.drop_column("notification_outbox", "provider_event_at")
    op.drop_column("notification_outbox", "provider_delivery_state")
    op.drop_column("notification_outbox", "provider_message_id")
