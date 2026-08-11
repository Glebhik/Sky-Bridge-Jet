"""Enforce trip-passenger customer ownership at the database level.

Adds a shared ``customer_id`` column to ``trip_passengers`` constrained by two
composite foreign keys so PostgreSQL guarantees that an associated passenger and
trip request resolve to the same customer, independent of the service layer.

Revision ID: 20260810_0003
Revises: 20260810_0002
Create Date: 2026-08-10 00:03:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "20260810_0003"
down_revision: str | Sequence[str] | None = "20260810_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the composite ownership invariant to trip_passengers."""
    from alembic import op

    op.create_unique_constraint(
        "uq_trip_requests_id_customer", "trip_requests", ["id", "customer_id"]
    )
    op.create_unique_constraint("uq_passengers_id_customer", "passengers", ["id", "customer_id"])

    # Add nullable first, backfill from the owning passenger for any existing
    # rows, then enforce NOT NULL so the migration is deterministic regardless of
    # pre-existing data.
    op.add_column("trip_passengers", sa.Column("customer_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE trip_passengers AS tp "
            "SET customer_id = p.customer_id "
            "FROM passengers AS p "
            "WHERE p.id = tp.passenger_id"
        )
    )
    op.alter_column("trip_passengers", "customer_id", nullable=False)
    op.create_index("ix_trip_passengers_customer_id", "trip_passengers", ["customer_id"])

    op.create_foreign_key(
        "fk_trip_passengers_trip_request_customer",
        "trip_passengers",
        "trip_requests",
        ["trip_request_id", "customer_id"],
        ["id", "customer_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_trip_passengers_passenger_customer",
        "trip_passengers",
        "passengers",
        ["passenger_id", "customer_id"],
        ["id", "customer_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove the composite ownership invariant from trip_passengers."""
    from alembic import op

    op.drop_constraint(
        "fk_trip_passengers_passenger_customer", "trip_passengers", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_trip_passengers_trip_request_customer", "trip_passengers", type_="foreignkey"
    )
    op.drop_index("ix_trip_passengers_customer_id", table_name="trip_passengers")
    op.drop_column("trip_passengers", "customer_id")
    op.drop_constraint("uq_passengers_id_customer", "passengers", type_="unique")
    op.drop_constraint("uq_trip_requests_id_customer", "trip_requests", type_="unique")
