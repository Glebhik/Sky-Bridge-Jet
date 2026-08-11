"""Add the Phase 3 operator offers (quotes) domain.

Adds the ``operator_offers`` table with monetary-integrity check constraints,
composite operator/aircraft ownership enforcement, and partial unique indexes
for the single-selected-offer and duplicate-active-offer invariants.

Revision ID: 20260811_0004
Revises: 20260810_0003
Create Date: 2026-08-11 00:04:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0004"
down_revision: str | Sequence[str] | None = "20260810_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

offer_status = postgresql.ENUM(
    "DRAFT", "SUBMITTED", "WITHDRAWN", "SELECTED", name="offer_status", create_type=False
)


def upgrade() -> None:
    """Create the operator_offers table and its commercial-integrity constraints."""
    from alembic import op

    bind = op.get_bind()
    offer_status.create(bind, checkfirst=True)

    # Composite unique target for the operator/aircraft ownership foreign key.
    op.create_unique_constraint("uq_aircraft_id_operator", "aircraft", ["id", "operator_id"])

    op.create_table(
        "operator_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_request_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("aircraft_id", sa.Uuid(), nullable=False),
        sa.Column("status", offer_status, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("operator_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("platform_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_legal_name", sa.String(length=200), nullable=False),
        sa.Column("aircraft_registration", sa.String(length=20), nullable=False),
        sa.Column("aircraft_manufacturer", sa.String(length=100), nullable=False),
        sa.Column("aircraft_model", sa.String(length=100), nullable=False),
        sa.Column("aircraft_category", sa.String(length=32), nullable=False),
        sa.Column("operator_notes", sa.String(length=1000), nullable=True),
        sa.Column("cancellation_policy", sa.String(length=1000), nullable=True),
        sa.Column("included_services", sa.Text(), nullable=True),
        sa.Column("excluded_services", sa.Text(), nullable=True),
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
            "currency IN ('EUR', 'GBP', 'USD')", name="ck_operator_offers_currency_supported"
        ),
        sa.CheckConstraint(
            "operator_amount_minor >= 0",
            name="ck_operator_offers_operator_amount_non_negative",
        ),
        sa.CheckConstraint(
            "platform_fee_minor >= 0", name="ck_operator_offers_platform_fee_non_negative"
        ),
        sa.CheckConstraint("tax_amount_minor >= 0", name="ck_operator_offers_tax_non_negative"),
        sa.CheckConstraint("total_amount_minor >= 0", name="ck_operator_offers_total_non_negative"),
        sa.CheckConstraint(
            "total_amount_minor = operator_amount_minor + platform_fee_minor + tax_amount_minor",
            name="ck_operator_offers_total_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["aircraft_id", "operator_id"],
            ["aircraft.id", "aircraft.operator_id"],
            name="fk_operator_offers_aircraft_operator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trip_request_id"], ["trip_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operator_offers_aircraft_id", "operator_offers", ["aircraft_id"], unique=False
    )
    op.create_index(
        "ix_operator_offers_operator_id", "operator_offers", ["operator_id"], unique=False
    )
    op.create_index(
        "ix_operator_offers_trip_request_id", "operator_offers", ["trip_request_id"], unique=False
    )
    op.create_index(
        "uq_operator_offers_active_aircraft",
        "operator_offers",
        ["trip_request_id", "operator_id", "aircraft_id"],
        unique=True,
        postgresql_where="status IN ('DRAFT', 'SUBMITTED', 'SELECTED')",
    )
    op.create_index(
        "uq_operator_offers_one_selected_per_trip",
        "operator_offers",
        ["trip_request_id"],
        unique=True,
        postgresql_where="status = 'SELECTED'",
    )


def downgrade() -> None:
    """Remove the Phase 3 operator offers schema and its enum type."""
    from alembic import op

    op.drop_index("uq_operator_offers_one_selected_per_trip", table_name="operator_offers")
    op.drop_index("uq_operator_offers_active_aircraft", table_name="operator_offers")
    op.drop_index("ix_operator_offers_trip_request_id", table_name="operator_offers")
    op.drop_index("ix_operator_offers_operator_id", table_name="operator_offers")
    op.drop_index("ix_operator_offers_aircraft_id", table_name="operator_offers")
    op.drop_table("operator_offers")
    op.drop_constraint("uq_aircraft_id_operator", "aircraft", type_="unique")

    offer_status.drop(op.get_bind(), checkfirst=True)
