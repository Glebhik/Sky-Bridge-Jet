"""Add durable provider-attempt identity to the payment operation ledger.

Revision ID: 20260827_0010
Revises: 20260813_0009
Create Date: 2026-08-27 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0010"
down_revision: str | Sequence[str] | None = "20260813_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_provider_kind = postgresql.ENUM(
    "FAKE", "STRIPE", name="payment_provider_kind", create_type=False
)


def upgrade() -> None:
    from alembic import op

    # PostgreSQL enum additions must be visible before rows can use the values.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE payment_operation_result ADD VALUE IF NOT EXISTS 'PENDING'")
        op.execute("ALTER TYPE payment_operation_result ADD VALUE IF NOT EXISTS 'UNKNOWN'")

    op.add_column(
        "payment_operations",
        sa.Column("provider_kind", payment_provider_kind, nullable=True),
    )
    op.add_column("payment_operations", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.add_column(
        "payment_operations",
        sa.Column("attempt_count", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "payment_operations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE payment_operations AS operation
        SET provider_kind = payment.payment_provider,
            correlation_id = md5(operation.id::text)::uuid,
            attempt_count = 1
        FROM payments AS payment
        WHERE payment.id = operation.payment_id
        """
    )
    op.alter_column("payment_operations", "provider_kind", nullable=False)
    op.alter_column("payment_operations", "correlation_id", nullable=False)
    op.create_unique_constraint(
        "uq_payment_operations_correlation_id",
        "payment_operations",
        ["correlation_id"],
    )


def downgrade() -> None:
    from alembic import op

    op.drop_constraint("uq_payment_operations_correlation_id", "payment_operations", type_="unique")
    op.drop_column("payment_operations", "updated_at")
    op.drop_column("payment_operations", "attempt_count")
    op.drop_column("payment_operations", "correlation_id")
    op.drop_column("payment_operations", "provider_kind")
    # PostgreSQL does not safely remove enum values in-place. PENDING/UNKNOWN are
    # intentionally retained on downgrade; no rows can reference them afterward.
