from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.modules.core_aviation.domain import (
    AircraftCategory,
    AircraftStatus,
    CustomerStatus,
    CustomerType,
    OperatorStatus,
    PetType,
    TripRequestStatus,
    normalize_email,
    normalize_registration,
    normalize_required_text,
    validate_airport_code,
    validate_aware_datetime,
    validate_country_code,
    validate_currency_code,
    validate_language_tag,
    validate_timezone,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampedEntity:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class Customer(TimestampedEntity, Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_type: Mapped[CustomerType] = mapped_column(
        Enum(CustomerType, name="customer_type"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    primary_email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    primary_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    preferred_currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Etc/UTC", nullable=False)
    status: Mapped[CustomerStatus] = mapped_column(
        Enum(CustomerStatus, name="customer_status"),
        default=CustomerStatus.ACTIVE,
        nullable=False,
    )

    passengers: Mapped[list[Passenger]] = relationship(
        back_populates="customer", passive_deletes=True
    )
    trip_requests: Mapped[list[TripRequest]] = relationship(
        back_populates="customer", passive_deletes=True
    )

    @validates("primary_email")
    def validate_primary_email(self, _key: str, value: str) -> str:
        return normalize_email(value)

    @validates("display_name")
    def validate_display_name(self, _key: str, value: str) -> str:
        return normalize_required_text(value, field_name="Display name")

    @validates("preferred_language")
    def validate_preferred_language(self, _key: str, value: str) -> str:
        return validate_language_tag(value)

    @validates("preferred_currency")
    def validate_preferred_currency(self, _key: str, value: str) -> str:
        return validate_currency_code(value)

    @validates("timezone")
    def validate_customer_timezone(self, _key: str, value: str) -> str:
        return validate_timezone(value)


class Passenger(TimestampedEntity, Base):
    __tablename__ = "passengers"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(2), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="passengers")
    trip_associations: Mapped[list[TripPassenger]] = relationship(
        back_populates="passenger", passive_deletes=True
    )

    @validates("nationality")
    def validate_nationality(self, _key: str, value: str | None) -> str | None:
        return validate_country_code(value) if value is not None else None

    @validates("first_name", "last_name")
    def validate_passenger_name(self, key: str, value: str) -> str:
        return normalize_required_text(value, field_name=key.replace("_", " ").title())

    @validates("contact_email")
    def validate_contact_email(self, _key: str, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else None


class Airport(TimestampedEntity, Base):
    __tablename__ = "airports"
    __table_args__ = (
        UniqueConstraint("icao_code", name="uq_airports_icao_code"),
        UniqueConstraint("iata_code", name="uq_airports_iata_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    icao_code: Mapped[str] = mapped_column(String(4), index=True, nullable=False)
    iata_code: Mapped[str | None] = mapped_column(String(3), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    origin_legs: Mapped[list[TripLeg]] = relationship(
        foreign_keys="TripLeg.origin_airport_id", passive_deletes=True
    )
    destination_legs: Mapped[list[TripLeg]] = relationship(
        foreign_keys="TripLeg.destination_airport_id", passive_deletes=True
    )

    @validates("icao_code")
    def validate_icao_code(self, _key: str, value: str) -> str:
        return validate_airport_code(value, field_name="icao_code", length=4)

    @validates("iata_code")
    def validate_iata_code(self, _key: str, value: str | None) -> str | None:
        return (
            validate_airport_code(value, field_name="iata_code", length=3)
            if value is not None
            else None
        )

    @validates("country_code")
    def validate_airport_country_code(self, _key: str, value: str) -> str:
        return validate_country_code(value)

    @validates("timezone")
    def validate_airport_timezone(self, _key: str, value: str) -> str:
        return validate_timezone(value)


class Operator(TimestampedEntity, Base):
    __tablename__ = "operators"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    legal_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[OperatorStatus] = mapped_column(
        Enum(OperatorStatus, name="operator_status"),
        default=OperatorStatus.ACTIVE,
        nullable=False,
    )

    aircraft: Mapped[list[Aircraft]] = relationship(back_populates="operator", passive_deletes=True)

    @validates("country_code")
    def validate_operator_country_code(self, _key: str, value: str) -> str:
        return validate_country_code(value)

    @validates("legal_name")
    def validate_legal_name(self, _key: str, value: str) -> str:
        return normalize_required_text(value, field_name="Legal name")

    @validates("trading_name")
    def validate_trading_name(self, _key: str, value: str | None) -> str | None:
        return (
            normalize_required_text(value, field_name="Trading name") if value is not None else None
        )

    @validates("contact_email")
    def validate_operator_contact_email(self, _key: str, value: str) -> str:
        return normalize_email(value)


class Aircraft(TimestampedEntity, Base):
    __tablename__ = "aircraft"
    __table_args__ = (
        CheckConstraint("passenger_capacity > 0", name="ck_aircraft_capacity_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("operators.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[AircraftCategory] = mapped_column(
        Enum(AircraftCategory, name="aircraft_category"), nullable=False
    )
    registration: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    passenger_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AircraftStatus] = mapped_column(
        Enum(AircraftStatus, name="aircraft_status"),
        default=AircraftStatus.ACTIVE,
        nullable=False,
    )

    operator: Mapped[Operator] = relationship(back_populates="aircraft")

    @validates("registration")
    def validate_registration(self, _key: str, value: str) -> str:
        return normalize_registration(value)

    @validates("manufacturer", "model")
    def validate_aircraft_identity(self, key: str, value: str) -> str:
        return normalize_required_text(value, field_name=key.title())

    @validates("passenger_capacity")
    def validate_passenger_capacity(self, _key: str, value: int) -> int:
        if value <= 0:
            raise ValueError("Aircraft passenger capacity must be greater than zero")
        return value


class TripRequest(TimestampedEntity, Base):
    __tablename__ = "trip_requests"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[TripRequestStatus] = mapped_column(
        Enum(TripRequestStatus, name="trip_request_status"),
        default=TripRequestStatus.DRAFT,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    baggage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    catering_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ground_transport_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    special_assistance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="trip_requests")
    legs: Mapped[list[TripLeg]] = relationship(
        back_populates="trip_request",
        cascade="all, delete-orphan",
        order_by="TripLeg.sequence",
        passive_deletes=True,
    )
    passenger_associations: Mapped[list[TripPassenger]] = relationship(
        back_populates="trip_request", cascade="all, delete-orphan", passive_deletes=True
    )
    pet_requirement: Mapped[TripPetRequirement | None] = relationship(
        back_populates="trip_request",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )

    __mapper_args__ = {"version_id_col": version}


class TripLeg(TimestampedEntity, Base):
    __tablename__ = "trip_legs"
    __table_args__ = (
        UniqueConstraint("trip_request_id", "sequence", name="uq_trip_legs_sequence"),
        CheckConstraint(
            "origin_airport_id <> destination_airport_id",
            name="ck_trip_legs_different_airports",
        ),
        CheckConstraint("passenger_count > 0", name="ck_trip_legs_passenger_count_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trip_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("trip_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_airport_id: Mapped[UUID] = mapped_column(
        ForeignKey("airports.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    destination_airport_id: Mapped[UUID] = mapped_column(
        ForeignKey("airports.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    passenger_count: Mapped[int] = mapped_column(Integer, nullable=False)

    trip_request: Mapped[TripRequest] = relationship(back_populates="legs")
    origin_airport: Mapped[Airport] = relationship(
        foreign_keys=[origin_airport_id], back_populates="origin_legs"
    )
    destination_airport: Mapped[Airport] = relationship(
        foreign_keys=[destination_airport_id], back_populates="destination_legs"
    )

    @validates("departure_at")
    def validate_departure_at(self, _key: str, value: datetime) -> datetime:
        return validate_aware_datetime(value)

    @validates("origin_timezone", "destination_timezone")
    def validate_leg_timezone(self, _key: str, value: str) -> str:
        return validate_timezone(value)


class TripPassenger(Base):
    __tablename__ = "trip_passengers"

    trip_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("trip_requests.id", ondelete="CASCADE"), primary_key=True
    )
    passenger_id: Mapped[UUID] = mapped_column(
        ForeignKey("passengers.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    trip_request: Mapped[TripRequest] = relationship(back_populates="passenger_associations")
    passenger: Mapped[Passenger] = relationship(back_populates="trip_associations")


class TripPetRequirement(Base):
    __tablename__ = "trip_pet_requirements"
    __table_args__ = (CheckConstraint("weight_kg > 0", name="ck_trip_pet_weight_positive"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trip_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("trip_requests.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    pet_type: Mapped[PetType] = mapped_column(Enum(PetType, name="pet_type"), nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    trip_request: Mapped[TripRequest] = relationship(back_populates="pet_requirement")
