"""Add the Phase 5 payment & settlement core domain.

Adds the ``payments`` aggregate (one per booking) with an immutable commercial
snapshot bound to the booking by a composite foreign key, monetary-integrity and
captured<=authorized / refunded<=captured check constraints, and the
``payment_operations`` idempotency/attempt ledger. No real funds move.

Revision ID: 20260811_0006
Revises: 20260811_0005
Create Date: 2026-08-11 00:06:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0006"
down_revision: str | Sequence[str] | None = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_status = postgresql.ENUM(
    "CREATED",
    "AUTHORIZED",
    "AUTHORIZATION_FAILED",
    "CAPTURED",
    "CAPTURE_FAILED",
    "CANCELLED",
    "PARTIALLY_REFUNDED",
    "REFUNDED",
    name="payment_status",
    create_type=False,
)
payment_operation_type = postgresql.ENUM(
    "AUTHORIZE", "CAPTURE", "VOID", "REFUND", name="payment_operation_type", create_type=False
)
payment_operation_result = postgresql.ENUM(
    "SUCCEEDED", "FAILED", name="payment_operation_result", create_type=False
)


def upgrade() -> None:
    """Create the payments and payment_operations tables and their constraints."""
    from alembic import op

    bind = op.get_bind()
    payment_status.create(bind, checkfirst=True)
    payment_operation_type.create(bind, checkfirst=True)
    payment_operation_result.create(bind, checkfirst=True)

    # Composite unique target must exist before the payments composite FK.
    op.create_unique_constraint(
        "uq_bookings_commercial_snapshot",
        "bookings",
        [
            "id",
            "currency",
            "operator_amount_minor",
            "platform_fee_minor",
            "tax_amount_minor",
            "total_amount_minor",
        ],
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=32), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("operator_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("platform_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("authorized_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("captured_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("refunded_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("provider_payment_reference", sa.String(length=200), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            "currency IN ('EUR', 'GBP', 'USD')", name="ck_payments_currency_supported"
        ),
        sa.CheckConstraint(
            "authorized_amount_minor IS NULL OR authorized_amount_minor >= 0",
            name="ck_payments_authorized_non_neg",
        ),
        sa.CheckConstraint(
            "authorized_amount_minor IS NULL OR captured_amount_minor <= authorized_amount_minor",
            name="ck_payments_captured_le_authorized",
        ),
        sa.CheckConstraint("captured_amount_minor >= 0", name="ck_payments_captured_non_neg"),
        sa.CheckConstraint(
            "operator_amount_minor >= 0", name="ck_payments_operator_amount_non_neg"
        ),
        sa.CheckConstraint("platform_fee_minor >= 0", name="ck_payments_platform_fee_non_neg"),
        sa.CheckConstraint(
            "refunded_amount_minor <= captured_amount_minor",
            name="ck_payments_refunded_le_captured",
        ),
        sa.CheckConstraint("refunded_amount_minor >= 0", name="ck_payments_refunded_non_neg"),
        sa.CheckConstraint("tax_amount_minor >= 0", name="ck_payments_tax_non_neg"),
        sa.CheckConstraint(
            "total_amount_minor = operator_amount_minor + platform_fee_minor + tax_amount_minor",
            name="ck_payments_total_consistent",
        ),
        sa.CheckConstraint("total_amount_minor >= 0", name="ck_payments_total_non_neg"),
        sa.ForeignKeyConstraint(
            [
                "booking_id",
                "currency",
                "operator_amount_minor",
                "platform_fee_minor",
                "tax_amount_minor",
                "total_amount_minor",
            ],
            [
                "bookings.id",
                "bookings.currency",
                "bookings.operator_amount_minor",
                "bookings.platform_fee_minor",
                "bookings.tax_amount_minor",
                "bookings.total_amount_minor",
            ],
            name="fk_payments_booking_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_payments_booking"),
        sa.UniqueConstraint("reference", name="uq_payments_reference"),
    )

    op.create_table(
        "payment_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("operation", payment_operation_type, nullable=False),
        sa.Column("result", payment_operation_result, nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("provider_reference", sa.String(length=200), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_payment_operations_amount_non_neg"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payment_operations_idempotency_key"),
    )
    op.create_index(
        "ix_payment_operations_payment_id", "payment_operations", ["payment_id"], unique=False
    )


def downgrade() -> None:
    """Remove the Phase 5 payment schema and its enum types."""
    from alembic import op

    op.drop_index("ix_payment_operations_payment_id", table_name="payment_operations")
    op.drop_table("payment_operations")
    op.drop_table("payments")
    op.drop_constraint("uq_bookings_commercial_snapshot", "bookings", type_="unique")

    bind = op.get_bind()
    payment_operation_result.drop(bind, checkfirst=True)
    payment_operation_type.drop(bind, checkfirst=True)
    payment_status.drop(bind, checkfirst=True)
