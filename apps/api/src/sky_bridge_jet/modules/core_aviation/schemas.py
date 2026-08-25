from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    validate_country_code,
    validate_currency_code,
    validate_language_tag,
    validate_timezone,
    validate_trip_leg,
)

ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerCreate(ApiModel):
    customer_type: CustomerType
    display_name: ShortText
    primary_email: Annotated[str, Field(max_length=320)]
    primary_phone: Annotated[str, Field(max_length=40)] | None = None
    preferred_language: Annotated[str, Field(max_length=16)] = "en"
    preferred_currency: Annotated[str, Field(max_length=3)] = "EUR"
    timezone: Annotated[str, Field(max_length=64)] = "Etc/UTC"

    @field_validator("primary_email")
    @classmethod
    def normalize_primary_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="Display name")

    @field_validator("preferred_language")
    @classmethod
    def validate_preferred_language(cls, value: str) -> str:
        return validate_language_tag(value)

    @field_validator("preferred_currency")
    @classmethod
    def validate_preferred_currency(cls, value: str) -> str:
        return validate_currency_code(value)

    @field_validator("timezone")
    @classmethod
    def validate_customer_timezone(cls, value: str) -> str:
        return validate_timezone(value)


class CustomerResponse(ApiModel):
    id: UUID
    customer_type: CustomerType
    display_name: str
    primary_email: str
    primary_phone: str | None
    preferred_language: str
    preferred_currency: str
    timezone: str
    status: CustomerStatus
    created_at: datetime
    updated_at: datetime


class PassengerCreate(ApiModel):
    # Optional client-supplied confirmation only. The authoritative customer is derived
    # server-side from the authenticated principal + validated active organization in
    # `resolve_write_customer`; omitting this lets a first-time customer create without
    # discovering an internal customer UUID, while a supplied *mismatching* value is still
    # rejected/concealed exactly as before (tenant isolation unchanged).
    customer_id: UUID | None = None
    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)]
    date_of_birth: date | None = None
    nationality: Annotated[str, Field(max_length=2)] | None = None
    contact_email: Annotated[str, Field(max_length=320)] | None = None
    contact_phone: Annotated[str, Field(max_length=40)] | None = None

    @field_validator("nationality")
    @classmethod
    def validate_passenger_nationality(cls, value: str | None) -> str | None:
        return validate_country_code(value) if value is not None else None

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_passenger_names(cls, value: str) -> str:
        return normalize_required_text(value, field_name="Passenger name")

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else None


class PassengerResponse(ApiModel):
    id: UUID
    customer_id: UUID
    first_name: str
    last_name: str
    date_of_birth: date | None
    nationality: str | None
    contact_email: str | None
    contact_phone: str | None
    created_at: datetime
    updated_at: datetime


class AirportResponse(ApiModel):
    id: UUID
    icao_code: str
    iata_code: str | None
    name: str
    city: str
    country_code: str
    latitude: Decimal
    longitude: Decimal
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OperatorCreate(ApiModel):
    legal_name: ShortText
    trading_name: Annotated[str, Field(max_length=200)] | None = None
    country_code: Annotated[str, Field(max_length=2)]
    contact_email: Annotated[str, Field(max_length=320)]
    contact_phone: Annotated[str, Field(max_length=40)] | None = None

    @field_validator("country_code")
    @classmethod
    def validate_operator_country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("legal_name")
    @classmethod
    def normalize_legal_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="Legal name")

    @field_validator("trading_name")
    @classmethod
    def normalize_trading_name(cls, value: str | None) -> str | None:
        return (
            normalize_required_text(value, field_name="Trading name") if value is not None else None
        )

    @field_validator("contact_email")
    @classmethod
    def normalize_operator_email(cls, value: str) -> str:
        return normalize_email(value)


class OperatorResponse(ApiModel):
    id: UUID
    legal_name: str
    trading_name: str | None
    country_code: str
    contact_email: str
    contact_phone: str | None
    status: OperatorStatus
    created_at: datetime
    updated_at: datetime


class AircraftCreate(ApiModel):
    operator_id: UUID
    manufacturer: Annotated[str, Field(min_length=1, max_length=100)]
    model: Annotated[str, Field(min_length=1, max_length=100)]
    category: AircraftCategory
    registration: Annotated[str, Field(max_length=20)]
    passenger_capacity: Annotated[int, Field(gt=0, le=1_000)]

    @field_validator("registration")
    @classmethod
    def normalize_aircraft_registration(cls, value: str) -> str:
        return normalize_registration(value)

    @field_validator("manufacturer", "model")
    @classmethod
    def normalize_aircraft_identity(cls, value: str) -> str:
        return normalize_required_text(value, field_name="Aircraft identity")


class AircraftResponse(ApiModel):
    id: UUID
    operator_id: UUID
    manufacturer: str
    model: str
    category: AircraftCategory
    registration: str
    passenger_capacity: int
    status: AircraftStatus
    created_at: datetime
    updated_at: datetime


class PetRequirementCreate(ApiModel):
    pet_type: PetType
    approximate_weight_kg: Annotated[Decimal, Field(gt=0, le=200)] | None = None
    notes: Annotated[str, Field(max_length=1_000)] | None = None


class PetRequirementResponse(ApiModel):
    pet_type: PetType
    approximate_weight_kg: Decimal | None
    notes: str | None


class TripRequirementsCreate(ApiModel):
    baggage_notes: Annotated[str, Field(max_length=2_000)] | None = None
    catering_notes: Annotated[str, Field(max_length=2_000)] | None = None
    ground_transport_requested: bool = False
    special_assistance_notes: Annotated[str, Field(max_length=2_000)] | None = None
    customer_notes: Annotated[str, Field(max_length=2_000)] | None = None
    pet: PetRequirementCreate | None = None


class TripRequirementsResponse(ApiModel):
    baggage_notes: str | None
    catering_notes: str | None
    ground_transport_requested: bool
    special_assistance_notes: str | None
    customer_notes: str | None
    pet_present: bool
    pet: PetRequirementResponse | None


class TripLegCreate(ApiModel):
    origin_airport_id: UUID
    destination_airport_id: UUID
    departure_at: datetime
    passenger_count: Annotated[int, Field(gt=0, le=1_000)]

    @model_validator(mode="after")
    def validate_leg(self) -> TripLegCreate:
        validate_trip_leg(
            origin_airport_id=self.origin_airport_id,
            destination_airport_id=self.destination_airport_id,
            departure_at=self.departure_at,
            passenger_count=self.passenger_count,
        )
        return self


class TripLegResponse(ApiModel):
    id: UUID
    sequence: int
    origin_airport_id: UUID
    destination_airport_id: UUID
    departure_at: datetime
    origin_timezone: str
    destination_timezone: str
    passenger_count: int
    created_at: datetime
    updated_at: datetime


class TripRequestCreate(ApiModel):
    # Optional client-supplied confirmation only — see PassengerCreate.customer_id. The
    # authoritative customer is derived server-side from the principal + validated active
    # organization; omission derives it, a mismatching value is still rejected/concealed.
    customer_id: UUID | None = None
    legs: Annotated[list[TripLegCreate], Field(min_length=1, max_length=20)]
    passenger_ids: list[UUID] = Field(default_factory=list)
    requirements: TripRequirementsCreate = Field(default_factory=TripRequirementsCreate)

    @field_validator("passenger_ids")
    @classmethod
    def passengers_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Passenger IDs must be unique")
        return value


class TripPassengerResponse(ApiModel):
    id: UUID
    first_name: str
    last_name: str


class TripRequestResponse(ApiModel):
    id: UUID
    customer_id: UUID
    status: TripRequestStatus
    version: int
    legs: list[TripLegResponse]
    passengers: list[TripPassengerResponse]
    requirements: TripRequirementsResponse
    created_at: datetime
    updated_at: datetime


class VersionedTripCommand(ApiModel):
    expected_version: Annotated[int, Field(ge=1)]


class ErrorBody(ApiModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody
