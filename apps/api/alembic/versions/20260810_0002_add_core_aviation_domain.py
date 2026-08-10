"""Add the Phase 2 core private-aviation domain.

Revision ID: 20260810_0002
Revises: 20260810_0001
Create Date: 2026-08-10 00:02:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0002"
down_revision: str | Sequence[str] | None = "20260810_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

customer_type = postgresql.ENUM(
    "INDIVIDUAL", "ORGANIZATION", name="customer_type", create_type=False
)
customer_status = postgresql.ENUM("ACTIVE", "INACTIVE", name="customer_status", create_type=False)
operator_status = postgresql.ENUM("ACTIVE", "INACTIVE", name="operator_status", create_type=False)
aircraft_category = postgresql.ENUM(
    "VERY_LIGHT_JET",
    "LIGHT_JET",
    "MIDSIZE_JET",
    "SUPER_MIDSIZE_JET",
    "HEAVY_JET",
    "ULTRA_LONG_RANGE",
    "VIP_AIRLINER",
    "TURBOPROP",
    name="aircraft_category",
    create_type=False,
)
aircraft_status = postgresql.ENUM("ACTIVE", "INACTIVE", name="aircraft_status", create_type=False)
trip_request_status = postgresql.ENUM(
    "DRAFT",
    "SUBMITTED",
    "QUOTING",
    "QUOTES_AVAILABLE",
    "QUOTE_SELECTED",
    "BOOKED",
    "CANCELLED",
    "EXPIRED",
    name="trip_request_status",
    create_type=False,
)
pet_type = postgresql.ENUM("DOG", "CAT", "OTHER", name="pet_type", create_type=False)


def upgrade() -> None:
    """Create persisted core entities and their aggregate-only dependent records."""
    from alembic import op

    bind = op.get_bind()
    customer_type.create(bind, checkfirst=True)
    customer_status.create(bind, checkfirst=True)
    operator_status.create(bind, checkfirst=True)
    aircraft_category.create(bind, checkfirst=True)
    aircraft_status.create(bind, checkfirst=True)
    trip_request_status.create(bind, checkfirst=True)
    pet_type.create(bind, checkfirst=True)

    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_type", customer_type, nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("primary_email", sa.String(length=320), nullable=False),
        sa.Column("primary_phone", sa.String(length=40), nullable=True),
        sa.Column("preferred_language", sa.String(length=16), nullable=False),
        sa.Column("preferred_currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", customer_status, nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_primary_email", "customers", ["primary_email"], unique=True)

    op.create_table(
        "airports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("icao_code", sa.String(length=4), nullable=False),
        sa.Column("iata_code", sa.String(length=3), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("iata_code", name="uq_airports_iata_code"),
        sa.UniqueConstraint("icao_code", name="uq_airports_icao_code"),
    )
    op.create_index("ix_airports_country_code", "airports", ["country_code"])
    op.create_index("ix_airports_iata_code", "airports", ["iata_code"])
    op.create_index("ix_airports_icao_code", "airports", ["icao_code"])

    op.create_table(
        "operators",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("trading_name", sa.String(length=200), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=False),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column("status", operator_status, nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legal_name"),
    )
    op.create_index("ix_operators_country_code", "operators", ["country_code"])

    op.create_table(
        "passengers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=2), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
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
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_passengers_customer_id", "passengers", ["customer_id"])

    op.create_table(
        "aircraft",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("manufacturer", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("category", aircraft_category, nullable=False),
        sa.Column("registration", sa.String(length=20), nullable=False),
        sa.Column("passenger_capacity", sa.Integer(), nullable=False),
        sa.Column("status", aircraft_status, nullable=False),
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
        sa.CheckConstraint("passenger_capacity > 0", name="ck_aircraft_capacity_positive"),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration"),
    )
    op.create_index("ix_aircraft_operator_id", "aircraft", ["operator_id"])

    op.create_table(
        "trip_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("status", trip_request_status, nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("baggage_notes", sa.Text(), nullable=True),
        sa.Column("catering_notes", sa.Text(), nullable=True),
        sa.Column("ground_transport_requested", sa.Boolean(), nullable=False),
        sa.Column("special_assistance_notes", sa.Text(), nullable=True),
        sa.Column("customer_notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trip_requests_customer_id", "trip_requests", ["customer_id"])

    op.create_table(
        "trip_legs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("origin_airport_id", sa.Uuid(), nullable=False),
        sa.Column("destination_airport_id", sa.Uuid(), nullable=False),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin_timezone", sa.String(length=64), nullable=False),
        sa.Column("destination_timezone", sa.String(length=64), nullable=False),
        sa.Column("passenger_count", sa.Integer(), nullable=False),
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
            "origin_airport_id <> destination_airport_id",
            name="ck_trip_legs_different_airports",
        ),
        sa.CheckConstraint("passenger_count > 0", name="ck_trip_legs_passenger_count_positive"),
        sa.ForeignKeyConstraint(["destination_airport_id"], ["airports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["origin_airport_id"], ["airports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trip_request_id"], ["trip_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_request_id", "sequence", name="uq_trip_legs_sequence"),
    )
    op.create_index("ix_trip_legs_destination_airport_id", "trip_legs", ["destination_airport_id"])
    op.create_index("ix_trip_legs_origin_airport_id", "trip_legs", ["origin_airport_id"])
    op.create_index("ix_trip_legs_trip_request_id", "trip_legs", ["trip_request_id"])

    op.create_table(
        "trip_passengers",
        sa.Column("trip_request_id", sa.Uuid(), nullable=False),
        sa.Column("passenger_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["passenger_id"], ["passengers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trip_request_id"], ["trip_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trip_request_id", "passenger_id"),
    )

    op.create_table(
        "trip_pet_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_request_id", sa.Uuid(), nullable=False),
        sa.Column("pet_type", pet_type, nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("weight_kg > 0", name="ck_trip_pet_weight_positive"),
        sa.ForeignKeyConstraint(["trip_request_id"], ["trip_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_request_id"),
    )


def downgrade() -> None:
    """Remove Phase 2 schema in dependency order; intended only for non-production rollback."""
    from alembic import op

    op.drop_table("trip_pet_requirements")
    op.drop_table("trip_passengers")
    op.drop_index("ix_trip_legs_trip_request_id", table_name="trip_legs")
    op.drop_index("ix_trip_legs_origin_airport_id", table_name="trip_legs")
    op.drop_index("ix_trip_legs_destination_airport_id", table_name="trip_legs")
    op.drop_table("trip_legs")
    op.drop_index("ix_trip_requests_customer_id", table_name="trip_requests")
    op.drop_table("trip_requests")
    op.drop_index("ix_aircraft_operator_id", table_name="aircraft")
    op.drop_table("aircraft")
    op.drop_index("ix_passengers_customer_id", table_name="passengers")
    op.drop_table("passengers")
    op.drop_index("ix_operators_country_code", table_name="operators")
    op.drop_table("operators")
    op.drop_index("ix_airports_icao_code", table_name="airports")
    op.drop_index("ix_airports_iata_code", table_name="airports")
    op.drop_index("ix_airports_country_code", table_name="airports")
    op.drop_table("airports")
    op.drop_index("ix_customers_primary_email", table_name="customers")
    op.drop_table("customers")

    bind = op.get_bind()
    pet_type.drop(bind, checkfirst=True)
    trip_request_status.drop(bind, checkfirst=True)
    aircraft_status.drop(bind, checkfirst=True)
    aircraft_category.drop(bind, checkfirst=True)
    operator_status.drop(bind, checkfirst=True)
    customer_status.drop(bind, checkfirst=True)
    customer_type.drop(bind, checkfirst=True)
