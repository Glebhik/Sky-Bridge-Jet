"""Add the minimal post-booking operational handoff aggregate.

Revision ID: 20260829_0012
Revises: 20260828_0011
Create Date: 2026-08-29 00:12:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260829_0012"
down_revision: str | Sequence[str] | None = "20260828_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

operation_status = postgresql.ENUM(
    "HANDOFF_CREATED",
    name="flight_operation_status",
    create_type=False,
)


def upgrade() -> None:
    from alembic import op

    operation_status.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "flight_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            operation_status,
            server_default="HANDOFF_CREATED",
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_flight_operations_booking"),
    )
    op.create_index("ix_flight_operations_created", "flight_operations", ["created_at", "id"])


def downgrade() -> None:
    from alembic import op

    op.drop_table("flight_operations")
    operation_status.drop(op.get_bind(), checkfirst=False)
