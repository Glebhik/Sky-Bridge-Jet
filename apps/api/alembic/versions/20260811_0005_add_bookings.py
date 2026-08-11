"""Add the Phase 4 booking & reservation orchestration domain.

Adds the ``bookings`` table with a commercial snapshot of the selected offer,
monetary-integrity check constraints, a composite foreign key guaranteeing the
booking's offer/trip/operator/aircraft agree, a unique internal reference, and a
partial unique index enforcing at most one active booking per trip request.

Revision ID: 20260811_0005
Revises: 20260811_0004
Create Date: 2026-08-11 00:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0005"
down_revision: str | Sequence[str] | None = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

booking_status = postgresql.ENUM(
    "PENDING_OPERATOR_CONFIRMATION",
    "CONFIRMED",
    "REJECTED",
    "CANCELLED",
    name="booking_status",
    create_type=False,
)
booking_rejection_reason = postgresql.ENUM(
    "AIRCRAFT_UNAVAILABLE",
    "SCHEDULE_CONFLICT",
    "OPERATIONAL_RESTRICTION",
    "COMMERCIAL_WITHDRAWAL",
    "OTHER",
    name="booking_rejection_reason",
    create_type=False,
)
booking_cancellation_actor = postgresql.ENUM(
    "CUSTOMER", "OPERATOR", "PLATFORM", name="booking_cancellation_actor", create_type=False
)
booking_cancellation_reason = postgresql.ENUM(
    "SCHEDULE_CHANGE",
    "NO_LONGER_REQUIRED",
    "OPERATOR_UNAVAILABLE",
    "OTHER",
    name="booking_cancellation_reason",
    create_type=False,
)


def upgrade() -> None:
    """Create the bookings table and its commercial-integrity constraints."""
    from alembic import op

    bind = op.get_bind()
    booking_status.create(bind, checkfirst=True)
    booking_rejection_reason.create(bind, checkfirst=True)
    booking_cancellation_actor.create(bind, checkfirst=True)
    booking_cancellation_reason.create(bind, checkfirst=True)

    # Composite unique target so the booking's composite foreign key can pin the
    # exact offer and force trip/operator/aircraft agreement.
    op.create_unique_constraint(
        "uq_operator_offers_booking_ref",
        "operator_offers",
        ["id", "trip_request_id", "operator_id", "aircraft_id"],
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=32), nullable=False),
        sa.Column("trip_request_id", sa.Uuid(), nullable=False),
        sa.Column("operator_offer_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("aircraft_id", sa.Uuid(), nullable=False),
        sa.Column("status", booking_status, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("operator_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("platform_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("offer_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_legal_name", sa.String(length=200), nullable=False),
        sa.Column("aircraft_registration", sa.String(length=20), nullable=False),
        sa.Column("aircraft_manufacturer", sa.String(length=100), nullable=False),
        sa.Column("aircraft_model", sa.String(length=100), nullable=False),
        sa.Column("aircraft_category", sa.String(length=32), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_confirmation_reference", sa.String(length=100), nullable=True),
        sa.Column("confirmation_note", sa.String(length=500), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", booking_rejection_reason, nullable=True),
        sa.Column("rejection_note", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_actor", booking_cancellation_actor, nullable=True),
        sa.Column("cancellation_reason", booking_cancellation_reason, nullable=True),
        sa.Column("cancellation_note", sa.String(length=500), nullable=True),
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
            "currency IN ('EUR', 'GBP', 'USD')", name="ck_bookings_currency_supported"
        ),
        sa.CheckConstraint(
            "operator_amount_minor >= 0", name="ck_bookings_operator_amount_non_neg"
        ),
        sa.CheckConstraint("platform_fee_minor >= 0", name="ck_bookings_platform_fee_non_neg"),
        sa.CheckConstraint("tax_amount_minor >= 0", name="ck_bookings_tax_non_neg"),
        sa.CheckConstraint("total_amount_minor >= 0", name="ck_bookings_total_non_neg"),
        sa.CheckConstraint(
            "total_amount_minor = operator_amount_minor + platform_fee_minor + tax_amount_minor",
            name="ck_bookings_total_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["operator_offer_id", "trip_request_id", "operator_id", "aircraft_id"],
            [
                "operator_offers.id",
                "operator_offers.trip_request_id",
                "operator_offers.operator_id",
                "operator_offers.aircraft_id",
            ],
            name="fk_bookings_offer_consistency",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["trip_request_id"], ["trip_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_bookings_reference"),
    )
    op.create_index("ix_bookings_operator_id", "bookings", ["operator_id"], unique=False)
    op.create_index(
        "ix_bookings_operator_offer_id", "bookings", ["operator_offer_id"], unique=False
    )
    op.create_index("ix_bookings_trip_request_id", "bookings", ["trip_request_id"], unique=False)
    op.create_index(
        "uq_bookings_one_active_per_trip",
        "bookings",
        ["trip_request_id"],
        unique=True,
        postgresql_where="status IN ('PENDING_OPERATOR_CONFIRMATION', 'CONFIRMED')",
    )


def downgrade() -> None:
    """Remove the Phase 4 bookings schema and its enum types."""
    from alembic import op

    op.drop_index("uq_bookings_one_active_per_trip", table_name="bookings")
    op.drop_index("ix_bookings_trip_request_id", table_name="bookings")
    op.drop_index("ix_bookings_operator_offer_id", table_name="bookings")
    op.drop_index("ix_bookings_operator_id", table_name="bookings")
    op.drop_table("bookings")
    op.drop_constraint("uq_operator_offers_booking_ref", "operator_offers", type_="unique")

    bind = op.get_bind()
    booking_cancellation_reason.drop(bind, checkfirst=True)
    booking_cancellation_actor.drop(bind, checkfirst=True)
    booking_rejection_reason.drop(bind, checkfirst=True)
    booking_status.drop(bind, checkfirst=True)
