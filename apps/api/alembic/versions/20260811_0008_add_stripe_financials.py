"""Add Phase 7 Stripe payment provider fields and operator financial onboarding.

Introduces the provider-neutral ``payment_provider_kind`` type and pins it on each
payment (existing rows are backfilled to ``FAKE`` — no payment is silently moved to
a PSP). Adds SCA/reconciliation columns to ``payments`` (``provider_status``,
``requires_customer_action``). Creates the financial-onboarding domain
(``operator_connected_accounts``) and the data-minimized webhook idempotency ledger
(``provider_webhook_events``). Existing operators get no connected account, so they
remain financially NOT_STARTED with no fabricated provider references and no
auto-approval. This is financial onboarding only — it never touches Phase 6 aviation
compliance state, and it stores no bank/identity/beneficial-owner data.

Revision ID: 20260811_0008
Revises: 20260811_0007
Create Date: 2026-08-11 00:08:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0008"
down_revision: str | Sequence[str] | None = "20260811_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Shared provider-kind type, referenced by payments and both financial tables.
payment_provider_kind = postgresql.ENUM(
    "FAKE", "STRIPE", name="payment_provider_kind", create_type=False
)
financial_onboarding_status = postgresql.ENUM(
    "NOT_STARTED",
    "ONBOARDING_PENDING",
    "REQUIREMENTS_DUE",
    "UNDER_REVIEW",
    "ENABLED",
    "RESTRICTED",
    "DISABLED",
    name="financial_onboarding_status",
    create_type=False,
)
webhook_processing_status = postgresql.ENUM(
    "RECEIVED",
    "PROCESSED",
    "IGNORED",
    "FAILED",
    name="webhook_processing_status",
    create_type=False,
)


def upgrade() -> None:
    """Create Phase 7 enum types, payment columns, and financial-onboarding tables."""
    from alembic import op

    bind = op.get_bind()
    payment_provider_kind.create(bind, checkfirst=True)
    financial_onboarding_status.create(bind, checkfirst=True)
    webhook_processing_status.create(bind, checkfirst=True)

    # Pin the provider on each payment. Backfill existing rows to FAKE via a
    # temporary server default, then drop it so the column matches the ORM model
    # (which sets the default in Python, not the database).
    op.add_column(
        "payments",
        sa.Column(
            "payment_provider",
            payment_provider_kind,
            nullable=False,
            server_default="FAKE",
        ),
    )
    op.alter_column("payments", "payment_provider", server_default=None)
    op.add_column(
        "payments",
        sa.Column("provider_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column(
            "requires_customer_action",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("payments", "requires_customer_action", server_default=None)

    op.create_table(
        "operator_connected_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("payment_provider", payment_provider_kind, nullable=False),
        sa.Column("provider_account_reference", sa.String(length=255), nullable=False),
        sa.Column("onboarding_status", financial_onboarding_status, nullable=False),
        sa.Column("charges_enabled", sa.Boolean(), nullable=False),
        sa.Column("payouts_enabled", sa.Boolean(), nullable=False),
        sa.Column("requirements_due", sa.Boolean(), nullable=False),
        sa.Column("account_country", sa.String(length=2), nullable=True),
        sa.Column("disabled_reason", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("synchronized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operator_id", "payment_provider", name="uq_operator_connected_accounts_operator"
        ),
        sa.UniqueConstraint(
            "provider_account_reference", name="uq_operator_connected_accounts_reference"
        ),
    )
    op.create_index(
        "ix_operator_connected_accounts_operator_id",
        "operator_connected_accounts",
        ["operator_id"],
        unique=False,
    )

    op.create_table(
        "provider_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_provider", payment_provider_kind, nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("status", webhook_processing_status, nullable=False),
        sa.Column("entity_reference", sa.String(length=255), nullable=True),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payment_provider", "provider_event_id", name="uq_provider_webhook_events_event"
        ),
    )


def downgrade() -> None:
    """Remove the Phase 7 financial-onboarding schema and payment provider fields."""
    from alembic import op

    op.drop_table("provider_webhook_events")
    op.drop_index(
        "ix_operator_connected_accounts_operator_id",
        table_name="operator_connected_accounts",
    )
    op.drop_table("operator_connected_accounts")
    op.drop_column("payments", "requires_customer_action")
    op.drop_column("payments", "provider_status")
    op.drop_column("payments", "payment_provider")

    bind = op.get_bind()
    webhook_processing_status.drop(bind, checkfirst=True)
    financial_onboarding_status.drop(bind, checkfirst=True)
    payment_provider_kind.drop(bind, checkfirst=True)
