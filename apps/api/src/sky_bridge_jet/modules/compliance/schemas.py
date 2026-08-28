from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sky_bridge_jet.modules.compliance.domain import (
    ActorType,
    AircraftAuthorizationStatus,
    AuthorityBasis,
    ComplianceAction,
    ComplianceEntityType,
    EffectiveEvidenceStatus,
    EligibilityReasonCode,
    EvidenceStatus,
    EvidenceType,
    OperatorAdmissionStatus,
    ReviewReasonCode,
    validate_validity_window,
)
from sky_bridge_jet.modules.core_aviation.domain import (
    validate_aware_datetime,
    validate_country_code,
)

Note = Annotated[str, Field(min_length=1, max_length=500)]
Reference = Annotated[str, Field(min_length=1, max_length=200)]
StorageReference = Annotated[str, Field(min_length=1, max_length=500)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -- Request-level review actions -------------------------------------------


class AdmissionReviewAction(StrEnum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SUSPEND = "SUSPEND"
    RESTORE = "RESTORE"


class AuthorizationReviewAction(StrEnum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SUSPEND = "SUSPEND"
    RESTORE = "RESTORE"


class EvidenceReviewAction(StrEnum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    VERIFY = "VERIFY"
    REJECT = "REJECT"


# -- Requests ---------------------------------------------------------------


class EvidenceCreate(ApiModel):
    evidence_type: EvidenceType
    aircraft_id: UUID | None = None
    authority_basis: AuthorityBasis | None = None
    reference_number: Reference | None = None
    issuing_authority: Reference | None = None
    jurisdiction: Annotated[str, Field(max_length=2)] | None = None
    insurer_name: Reference | None = None
    storage_object_reference: StorageReference | None = None
    effective_date: datetime | None = None
    expiry_date: datetime | None = None
    supersedes_evidence_id: UUID | None = None

    @field_validator("jurisdiction")
    @classmethod
    def _jurisdiction(cls, value: str | None) -> str | None:
        return validate_country_code(value) if value is not None else None

    @field_validator("effective_date", "expiry_date")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return validate_aware_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _window(self) -> EvidenceCreate:
        validate_validity_window(self.effective_date, self.expiry_date)
        return self


class AuthorizationCreate(ApiModel):
    authority_basis: AuthorityBasis


class AdmissionReviewCommand(ApiModel):
    action: AdmissionReviewAction
    actor_type: ActorType
    actor_reference: Reference | None = None
    reason_code: ReviewReasonCode | None = None
    note: Note | None = None


class AuthorizationReviewCommand(ApiModel):
    action: AuthorizationReviewAction
    actor_type: ActorType
    actor_reference: Reference | None = None
    reason_code: ReviewReasonCode | None = None
    note: Note | None = None


class EvidenceReviewCommand(ApiModel):
    action: EvidenceReviewAction
    actor_type: ActorType
    actor_reference: Reference | None = None
    reason_code: ReviewReasonCode | None = None
    note: Note | None = None


class PlatformAdmissionReview(ApiModel):
    """Browser-safe decision input; actor identity is derived from the principal."""

    model_config = ConfigDict(extra="forbid")
    action: AdmissionReviewAction
    reason_code: ReviewReasonCode | None = None
    note: Note | None = None


class PlatformEvidenceReview(ApiModel):
    model_config = ConfigDict(extra="forbid")
    action: EvidenceReviewAction
    reason_code: ReviewReasonCode | None = None
    note: Note | None = None


class PlatformAuthorizationReview(ApiModel):
    model_config = ConfigDict(extra="forbid")
    action: AuthorizationReviewAction
    reason_code: ReviewReasonCode | None = None
    note: Note | None = None


# -- Responses --------------------------------------------------------------


class OperatorAdmissionResponse(ApiModel):
    id: UUID
    operator_id: UUID
    status: OperatorAdmissionStatus
    reason_code: ReviewReasonCode | None
    review_note: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EvidenceResponse(ApiModel):
    id: UUID
    operator_id: UUID
    aircraft_id: UUID | None
    evidence_type: EvidenceType
    status: EvidenceStatus
    effective_status: EffectiveEvidenceStatus
    authority_basis: AuthorityBasis | None
    reference_number: str | None
    issuing_authority: str | None
    jurisdiction: str | None
    insurer_name: str | None
    storage_object_reference: str | None
    effective_date: datetime | None
    expiry_date: datetime | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    review_reason_code: ReviewReasonCode | None
    review_note: str | None
    superseded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AuthorizationResponse(ApiModel):
    id: UUID
    operator_id: UUID
    aircraft_id: UUID
    status: AircraftAuthorizationStatus
    authority_basis: AuthorityBasis
    reason_code: ReviewReasonCode | None
    review_note: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditEventResponse(ApiModel):
    id: UUID
    entity_type: ComplianceEntityType
    entity_id: UUID
    action: ComplianceAction
    previous_status: str | None
    new_status: str | None
    actor_type: ActorType
    actor_reference: str | None
    reason_code: ReviewReasonCode | None
    note: str | None
    created_at: datetime


class PlatformAdmissionView(ApiModel):
    id: UUID
    operator_id: UUID
    operator_legal_name: str
    operator_trading_name: str | None
    operator_country_code: str
    status: OperatorAdmissionStatus
    reason_code: ReviewReasonCode | None
    review_note: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformEvidenceView(ApiModel):
    id: UUID
    operator_id: UUID
    operator_legal_name: str
    operator_trading_name: str | None
    aircraft_id: UUID | None
    aircraft_registration: str | None
    evidence_type: EvidenceType
    status: EvidenceStatus
    effective_status: EffectiveEvidenceStatus
    authority_basis: AuthorityBasis | None
    reference_number: str | None
    issuing_authority: str | None
    jurisdiction: str | None
    insurer_name: str | None
    has_storage_object: bool
    effective_date: datetime | None
    expiry_date: datetime | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    review_reason_code: ReviewReasonCode | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class PlatformAuthorizationView(ApiModel):
    id: UUID
    operator_id: UUID
    operator_legal_name: str
    operator_trading_name: str | None
    aircraft_id: UUID
    aircraft_registration: str
    aircraft_manufacturer: str
    aircraft_model: str
    status: AircraftAuthorizationStatus
    authority_basis: AuthorityBasis
    reason_code: ReviewReasonCode | None
    review_note: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OperatorEligibilityResponse(ApiModel):
    operator_id: UUID
    eligible: bool
    reasons: list[EligibilityReasonCode]


class OperatorComplianceReadinessResponse(ApiModel):
    """Operator-safe readiness for the authenticated active organization."""

    admission_status: OperatorAdmissionStatus | None
    marketplace_eligible: bool
    blockers: list[EligibilityReasonCode]
    created_at: datetime | None
    updated_at: datetime | None


class OperatorAircraftEligibilityResponse(ApiModel):
    operator_id: UUID
    aircraft_id: UUID
    eligible: bool
    reasons: list[EligibilityReasonCode]
