from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sky_bridge_jet.modules.core_aviation.domain import validate_aware_datetime
from sky_bridge_jet.modules.offers.domain import (
    EffectiveOfferStatus,
    validate_supported_currency,
)

# Monetary amounts are integer minor units (e.g. cents). The upper bound keeps
# values comfortably inside BIGINT while rejecting implausible inputs.
MinorAmount = Annotated[int, Field(ge=0, le=10**15)]
ShortNote = Annotated[str, Field(min_length=1, max_length=1000)]
ServiceNote = Annotated[str, Field(min_length=1, max_length=2000)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _validate_currency(value: str) -> str:
    return validate_supported_currency(value)


def _validate_optional_aware(value: datetime | None) -> datetime | None:
    return validate_aware_datetime(value) if value is not None else None


class OperatorOfferCreate(ApiModel):
    trip_request_id: UUID
    operator_id: UUID
    aircraft_id: UUID
    currency: Annotated[str, Field(max_length=3)]
    operator_amount_minor: MinorAmount
    tax_amount_minor: MinorAmount = 0
    valid_until: datetime | None = None
    operator_notes: ShortNote | None = None
    cancellation_policy: ShortNote | None = None
    included_services: ServiceNote | None = None
    excluded_services: ServiceNote | None = None

    _currency = field_validator("currency")(_validate_currency)
    _valid_until = field_validator("valid_until")(_validate_optional_aware)


class OperatorOfferUpdate(ApiModel):
    """Partial update of a DRAFT offer; only supplied fields are applied."""

    currency: Annotated[str, Field(max_length=3)] | None = None
    operator_amount_minor: MinorAmount | None = None
    tax_amount_minor: MinorAmount | None = None
    valid_until: datetime | None = None
    operator_notes: ShortNote | None = None
    cancellation_policy: ShortNote | None = None
    included_services: ServiceNote | None = None
    excluded_services: ServiceNote | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str | None) -> str | None:
        return _validate_currency(value) if value is not None else None

    _valid_until = field_validator("valid_until")(_validate_optional_aware)


class OperatorOfferResponse(ApiModel):
    id: UUID
    trip_request_id: UUID
    operator_id: UUID
    aircraft_id: UUID
    status: EffectiveOfferStatus
    currency: str
    operator_amount_minor: int
    platform_fee_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    valid_until: datetime | None
    operator_legal_name: str
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    aircraft_category: str
    operator_notes: str | None
    cancellation_policy: str | None
    included_services: str | None
    excluded_services: str | None
    created_at: datetime
    updated_at: datetime
