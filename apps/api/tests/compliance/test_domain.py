from datetime import UTC, datetime, timedelta

import pytest

from sky_bridge_jet.modules.compliance.domain import (
    ActorType,
    AircraftAuthorizationStatus,
    EffectiveEvidenceStatus,
    EvidenceStatus,
    InvalidComplianceTransitionError,
    OperatorAdmissionStatus,
    UnauthorizedReviewActorError,
    effective_evidence_status,
    is_evidence_current,
    require_review_actor,
    validate_admission_transition,
    validate_authorization_transition,
    validate_evidence_transition,
    validate_validity_window,
)
from sky_bridge_jet.modules.core_aviation.domain import DomainValidationError

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        (OperatorAdmissionStatus.DRAFT, OperatorAdmissionStatus.SUBMITTED, True),
        (OperatorAdmissionStatus.SUBMITTED, OperatorAdmissionStatus.APPROVED, True),
        (OperatorAdmissionStatus.APPROVED, OperatorAdmissionStatus.SUSPENDED, True),
        (OperatorAdmissionStatus.SUSPENDED, OperatorAdmissionStatus.APPROVED, True),
        (OperatorAdmissionStatus.REJECTED, OperatorAdmissionStatus.SUBMITTED, True),
        (OperatorAdmissionStatus.DRAFT, OperatorAdmissionStatus.APPROVED, False),
        (OperatorAdmissionStatus.REJECTED, OperatorAdmissionStatus.APPROVED, False),
        (OperatorAdmissionStatus.APPROVED, OperatorAdmissionStatus.APPROVED, False),
    ],
)
def test_admission_transitions(
    current: OperatorAdmissionStatus, target: OperatorAdmissionStatus, allowed: bool
) -> None:
    if allowed:
        assert validate_admission_transition(current, target) == target
    else:
        with pytest.raises(InvalidComplianceTransitionError):
            validate_admission_transition(current, target)


def test_authorization_and_evidence_transitions() -> None:
    assert (
        validate_authorization_transition(
            AircraftAuthorizationStatus.SUBMITTED, AircraftAuthorizationStatus.APPROVED
        )
        == AircraftAuthorizationStatus.APPROVED
    )
    with pytest.raises(InvalidComplianceTransitionError):
        validate_authorization_transition(
            AircraftAuthorizationStatus.SUSPENDED, AircraftAuthorizationStatus.SUBMITTED
        )
    assert (
        validate_evidence_transition(EvidenceStatus.SUBMITTED, EvidenceStatus.VERIFIED)
        == EvidenceStatus.VERIFIED
    )
    with pytest.raises(InvalidComplianceTransitionError):
        validate_evidence_transition(EvidenceStatus.SUPERSEDED, EvidenceStatus.VERIFIED)


def test_review_actor_requires_human_authorization() -> None:
    assert require_review_actor(ActorType.PLATFORM_REVIEWER) is ActorType.PLATFORM_REVIEWER
    assert require_review_actor(ActorType.PRODUCT_OWNER) is ActorType.PRODUCT_OWNER
    for actor in (ActorType.SYSTEM, ActorType.OPERATOR):
        with pytest.raises(UnauthorizedReviewActorError):
            require_review_actor(actor)


def test_effective_expiration() -> None:
    past = _NOW - timedelta(days=1)
    future = _NOW + timedelta(days=1)
    assert is_evidence_current(EvidenceStatus.VERIFIED, future, now=_NOW) is True
    assert is_evidence_current(EvidenceStatus.VERIFIED, None, now=_NOW) is True
    assert is_evidence_current(EvidenceStatus.VERIFIED, past, now=_NOW) is False
    # Boundary: expired exactly at now.
    assert is_evidence_current(EvidenceStatus.VERIFIED, _NOW, now=_NOW) is False
    # Only verified evidence can be current.
    assert is_evidence_current(EvidenceStatus.SUBMITTED, future, now=_NOW) is False

    assert (
        effective_evidence_status(EvidenceStatus.VERIFIED, past, now=_NOW)
        == EffectiveEvidenceStatus.EXPIRED
    )
    assert (
        effective_evidence_status(EvidenceStatus.VERIFIED, future, now=_NOW)
        == EffectiveEvidenceStatus.VERIFIED
    )
    assert (
        effective_evidence_status(EvidenceStatus.SUBMITTED, past, now=_NOW)
        == EffectiveEvidenceStatus.SUBMITTED
    )


def test_validity_window() -> None:
    validate_validity_window(_NOW, _NOW + timedelta(days=1))
    validate_validity_window(None, None)
    with pytest.raises(DomainValidationError):
        validate_validity_window(_NOW, _NOW - timedelta(days=1))
