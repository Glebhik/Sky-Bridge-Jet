from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final

from sky_bridge_jet.modules.core_aviation.domain import DomainError, DomainValidationError

# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------


class OperatorAdmissionStatus(StrEnum):
    """Marketplace-admission lifecycle for an operator.

    APPROVED means "admitted to the Sky Bridge Jet marketplace under the current
    compliance procedure" — NOT a government certification that the operator is
    legally authorized to perform every possible flight.
    """

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class AircraftAuthorizationStatus(StrEnum):
    """Marketplace-admission lifecycle for one operator/aircraft combination."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class EvidenceStatus(StrEnum):
    """Persisted compliance-evidence lifecycle.

    EXPIRED is not persisted: expiration is derived from ``expiry_date`` during
    eligibility evaluation (see :class:`EffectiveEvidenceStatus`).
    """

    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EffectiveEvidenceStatus(StrEnum):
    """Evidence status presented to API consumers, including derived EXPIRED."""

    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class EvidenceType(StrEnum):
    """Provider-neutral compliance evidence types.

    OPERATING_AUTHORITY covers an operator's authority to conduct commercial
    operations (an AOC is the primary example, but the model is not hard-coded to
    a single jurisdiction's document).
    """

    OPERATING_AUTHORITY = "OPERATING_AUTHORITY"
    INSURANCE = "INSURANCE"
    AIRCRAFT_OPERATING_AUTHORITY = "AIRCRAFT_OPERATING_AUTHORITY"
    OTHER = "OTHER"


class AuthorityBasis(StrEnum):
    """Basis on which an operator may commercially offer an aircraft (not ownership)."""

    OWNED = "OWNED"
    LEASED = "LEASED"
    MANAGED = "MANAGED"
    OPERATED_UNDER_AGREEMENT = "OPERATED_UNDER_AGREEMENT"
    OTHER = "OTHER"


class ReviewReasonCode(StrEnum):
    """Controlled reviewer-supplied reason codes for rejections/suspensions."""

    DOCUMENT_MISSING = "DOCUMENT_MISSING"
    DOCUMENT_EXPIRED = "DOCUMENT_EXPIRED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    AUTHORITY_NOT_VERIFIED = "AUTHORITY_NOT_VERIFIED"
    INSURANCE_NOT_VERIFIED = "INSURANCE_NOT_VERIFIED"
    AIRCRAFT_AUTHORITY_NOT_VERIFIED = "AIRCRAFT_AUTHORITY_NOT_VERIFIED"
    INFORMATION_INCONSISTENT = "INFORMATION_INCONSISTENT"
    MANUAL_SUSPENSION = "MANUAL_SUSPENSION"
    OTHER = "OTHER"


class EligibilityReasonCode(StrEnum):
    """Structured, explainable reasons a (combination) is not marketplace-eligible."""

    OPERATOR_NOT_ADMITTED = "OPERATOR_NOT_ADMITTED"
    OPERATOR_UNDER_REVIEW = "OPERATOR_UNDER_REVIEW"
    OPERATOR_REJECTED = "OPERATOR_REJECTED"
    OPERATOR_SUSPENDED = "OPERATOR_SUSPENDED"
    AUTHORITY_NOT_VERIFIED = "AUTHORITY_NOT_VERIFIED"
    AUTHORITY_EXPIRED = "AUTHORITY_EXPIRED"
    INSURANCE_NOT_VERIFIED = "INSURANCE_NOT_VERIFIED"
    INSURANCE_EXPIRED = "INSURANCE_EXPIRED"
    AIRCRAFT_NOT_AUTHORIZED = "AIRCRAFT_NOT_AUTHORIZED"
    AIRCRAFT_AUTHORIZATION_SUSPENDED = "AIRCRAFT_AUTHORIZATION_SUSPENDED"
    AIRCRAFT_NOT_OPERATED_BY_OPERATOR = "AIRCRAFT_NOT_OPERATED_BY_OPERATOR"


class ActorType(StrEnum):
    """Provider-neutral actor abstraction while authentication is deferred.

    A review decision must be attributed to a human-authorized actor
    (PLATFORM_REVIEWER or PRODUCT_OWNER). An unauthenticated API does not by
    itself prove human authorization; a future auth layer binds these to real
    authenticated reviewers.
    """

    SYSTEM = "SYSTEM"
    OPERATOR = "OPERATOR"
    PLATFORM_REVIEWER = "PLATFORM_REVIEWER"
    PRODUCT_OWNER = "PRODUCT_OWNER"


class ComplianceEntityType(StrEnum):
    OPERATOR_ADMISSION = "OPERATOR_ADMISSION"
    COMPLIANCE_EVIDENCE = "COMPLIANCE_EVIDENCE"
    AIRCRAFT_AUTHORIZATION = "AIRCRAFT_AUTHORIZATION"


class ComplianceAction(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    REVIEW_STARTED = "REVIEW_STARTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    RESTORED = "RESTORED"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


_REVIEW_ACTOR_TYPES: Final[frozenset[ActorType]] = frozenset(
    {ActorType.PLATFORM_REVIEWER, ActorType.PRODUCT_OWNER}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ComplianceConflictError(DomainError):
    """Base for compliance lifecycle and gate conflicts (maps to 409)."""

    code = "compliance_conflict"


class InvalidComplianceTransitionError(ComplianceConflictError):
    """Raised when a compliance lifecycle transition is not permitted."""

    code = "invalid_compliance_state"


class UnauthorizedReviewActorError(ComplianceConflictError):
    """Raised when a review decision is not attributed to a human-authorized actor."""

    code = "review_actor_not_permitted"


class ComplianceGateError(ComplianceConflictError):
    """Raised when marketplace eligibility blocks a commercial action (offer/confirm)."""

    code = "compliance_not_satisfied"

    def __init__(self, message: str, reasons: list[EligibilityReasonCode]) -> None:
        super().__init__(message)
        self.reasons = reasons


# ---------------------------------------------------------------------------
# Transition tables
# ---------------------------------------------------------------------------

_ADMISSION_TRANSITIONS: Final[dict[OperatorAdmissionStatus, frozenset[OperatorAdmissionStatus]]] = {
    OperatorAdmissionStatus.DRAFT: frozenset({OperatorAdmissionStatus.SUBMITTED}),
    OperatorAdmissionStatus.SUBMITTED: frozenset(
        {
            OperatorAdmissionStatus.UNDER_REVIEW,
            OperatorAdmissionStatus.APPROVED,
            OperatorAdmissionStatus.REJECTED,
        }
    ),
    OperatorAdmissionStatus.UNDER_REVIEW: frozenset(
        {OperatorAdmissionStatus.APPROVED, OperatorAdmissionStatus.REJECTED}
    ),
    OperatorAdmissionStatus.APPROVED: frozenset({OperatorAdmissionStatus.SUSPENDED}),
    OperatorAdmissionStatus.SUSPENDED: frozenset({OperatorAdmissionStatus.APPROVED}),
    OperatorAdmissionStatus.REJECTED: frozenset({OperatorAdmissionStatus.SUBMITTED}),
}

_AUTHORIZATION_TRANSITIONS: Final[
    dict[AircraftAuthorizationStatus, frozenset[AircraftAuthorizationStatus]]
] = {
    AircraftAuthorizationStatus.DRAFT: frozenset({AircraftAuthorizationStatus.SUBMITTED}),
    AircraftAuthorizationStatus.SUBMITTED: frozenset(
        {
            AircraftAuthorizationStatus.UNDER_REVIEW,
            AircraftAuthorizationStatus.APPROVED,
            AircraftAuthorizationStatus.REJECTED,
        }
    ),
    AircraftAuthorizationStatus.UNDER_REVIEW: frozenset(
        {AircraftAuthorizationStatus.APPROVED, AircraftAuthorizationStatus.REJECTED}
    ),
    AircraftAuthorizationStatus.APPROVED: frozenset({AircraftAuthorizationStatus.SUSPENDED}),
    AircraftAuthorizationStatus.SUSPENDED: frozenset({AircraftAuthorizationStatus.APPROVED}),
    AircraftAuthorizationStatus.REJECTED: frozenset({AircraftAuthorizationStatus.SUBMITTED}),
}

_EVIDENCE_TRANSITIONS: Final[dict[EvidenceStatus, frozenset[EvidenceStatus]]] = {
    EvidenceStatus.SUBMITTED: frozenset(
        {
            EvidenceStatus.UNDER_REVIEW,
            EvidenceStatus.VERIFIED,
            EvidenceStatus.REJECTED,
            EvidenceStatus.SUPERSEDED,
        }
    ),
    EvidenceStatus.UNDER_REVIEW: frozenset(
        {EvidenceStatus.VERIFIED, EvidenceStatus.REJECTED, EvidenceStatus.SUPERSEDED}
    ),
    EvidenceStatus.VERIFIED: frozenset({EvidenceStatus.SUPERSEDED}),
    EvidenceStatus.REJECTED: frozenset({EvidenceStatus.SUPERSEDED}),
    EvidenceStatus.SUPERSEDED: frozenset(),
}


def validate_admission_transition(
    current: OperatorAdmissionStatus, target: OperatorAdmissionStatus
) -> OperatorAdmissionStatus:
    if target not in _ADMISSION_TRANSITIONS[current]:
        raise InvalidComplianceTransitionError(
            f"Operator admission cannot transition from {current.value} to {target.value}"
        )
    return target


def validate_authorization_transition(
    current: AircraftAuthorizationStatus, target: AircraftAuthorizationStatus
) -> AircraftAuthorizationStatus:
    if target not in _AUTHORIZATION_TRANSITIONS[current]:
        raise InvalidComplianceTransitionError(
            f"Aircraft authorization cannot transition from {current.value} to {target.value}"
        )
    return target


def validate_evidence_transition(current: EvidenceStatus, target: EvidenceStatus) -> EvidenceStatus:
    if target not in _EVIDENCE_TRANSITIONS[current]:
        raise InvalidComplianceTransitionError(
            f"Evidence cannot transition from {current.value} to {target.value}"
        )
    return target


def require_review_actor(actor_type: ActorType) -> ActorType:
    """Ensure a review decision is attributed to a human-authorized actor."""
    if actor_type not in _REVIEW_ACTOR_TYPES:
        raise UnauthorizedReviewActorError(
            "Review decisions require a PLATFORM_REVIEWER or PRODUCT_OWNER actor"
        )
    return actor_type


# ---------------------------------------------------------------------------
# Effective expiration
# ---------------------------------------------------------------------------


def is_evidence_current(
    status: EvidenceStatus, expiry_date: datetime | None, *, now: datetime
) -> bool:
    """Report whether verified evidence is currently valid (not expired)."""
    return status is EvidenceStatus.VERIFIED and (expiry_date is None or now < expiry_date)


def effective_evidence_status(
    status: EvidenceStatus, expiry_date: datetime | None, *, now: datetime
) -> EffectiveEvidenceStatus:
    """Map a stored evidence status to the effective status, deriving EXPIRED."""
    if status is EvidenceStatus.VERIFIED and expiry_date is not None and now >= expiry_date:
        return EffectiveEvidenceStatus.EXPIRED
    return EffectiveEvidenceStatus(status.value)


def validate_validity_window(effective_date: datetime | None, expiry_date: datetime | None) -> None:
    """Reject a validity window whose expiry precedes its effective date."""
    if effective_date is not None and expiry_date is not None and expiry_date < effective_date:
        raise DomainValidationError("Evidence expiry date must not precede its effective date")
