from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.compliance.domain import (
    AircraftAuthorizationStatus,
    EligibilityReasonCode,
    EvidenceStatus,
    EvidenceType,
    OperatorAdmissionStatus,
    is_evidence_current,
)
from sky_bridge_jet.modules.compliance.models import ComplianceEvidence
from sky_bridge_jet.modules.compliance.repositories import (
    ComplianceEvidenceRepository,
    OperatorAdmissionRepository,
    OperatorAircraftAuthorizationRepository,
)
from sky_bridge_jet.modules.core_aviation.models import Aircraft

# Configured Phase 6 marketplace-admission prerequisites. This is Sky Bridge Jet's
# own admission procedure, NOT a government certification, and NOT a
# jurisdiction-specific legal sufficiency rule.
_REQUIRED_OPERATOR_EVIDENCE = (EvidenceType.OPERATING_AUTHORITY, EvidenceType.INSURANCE)

_NOT_ADMITTED_REASONS = {
    OperatorAdmissionStatus.DRAFT: EligibilityReasonCode.OPERATOR_NOT_ADMITTED,
    OperatorAdmissionStatus.SUBMITTED: EligibilityReasonCode.OPERATOR_NOT_ADMITTED,
    OperatorAdmissionStatus.UNDER_REVIEW: EligibilityReasonCode.OPERATOR_UNDER_REVIEW,
    OperatorAdmissionStatus.REJECTED: EligibilityReasonCode.OPERATOR_REJECTED,
    OperatorAdmissionStatus.SUSPENDED: EligibilityReasonCode.OPERATOR_SUSPENDED,
}

_MISSING_EVIDENCE_REASON = {
    EvidenceType.OPERATING_AUTHORITY: EligibilityReasonCode.AUTHORITY_NOT_VERIFIED,
    EvidenceType.INSURANCE: EligibilityReasonCode.INSURANCE_NOT_VERIFIED,
}
_EXPIRED_EVIDENCE_REASON = {
    EvidenceType.OPERATING_AUTHORITY: EligibilityReasonCode.AUTHORITY_EXPIRED,
    EvidenceType.INSURANCE: EligibilityReasonCode.INSURANCE_EXPIRED,
}


@dataclass
class EligibilityDecision:
    eligible: bool
    reasons: list[EligibilityReasonCode] = field(default_factory=list)


class ComplianceEvaluator:
    """The single, explainable marketplace-eligibility decision point.

    Eligibility is evaluated from current effective state (admission status,
    verified-and-unexpired required evidence, aircraft authorization). Callers that
    gate a commercial action pass ``lock=True`` so a concurrent suspension
    serializes and cannot slip past.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.admissions = OperatorAdmissionRepository(session)
        self.evidence = ComplianceEvidenceRepository(session)
        self.authorizations = OperatorAircraftAuthorizationRepository(session)

    def evaluate_operator(
        self, operator_id: UUID, *, now: datetime | None = None, lock: bool = False
    ) -> EligibilityDecision:
        now = now or datetime.now(UTC)
        reasons: list[EligibilityReasonCode] = []

        admission = (
            self.admissions.get_by_operator_for_update(operator_id)
            if lock
            else self.admissions.get_by_operator(operator_id)
        )
        if admission is None:
            reasons.append(EligibilityReasonCode.OPERATOR_NOT_ADMITTED)
        elif admission.status is not OperatorAdmissionStatus.APPROVED:
            reasons.append(_NOT_ADMITTED_REASONS[admission.status])

        for evidence_type in _REQUIRED_OPERATOR_EVIDENCE:
            items = self.evidence.list_operator_level_by_type(operator_id, evidence_type)
            if not self._has_current_evidence(items, now=now):
                reasons.append(self._evidence_reason(items, evidence_type, now=now))

        return EligibilityDecision(eligible=not reasons, reasons=reasons)

    def evaluate_operator_aircraft(
        self,
        operator_id: UUID,
        aircraft_id: UUID,
        *,
        now: datetime | None = None,
        lock: bool = False,
    ) -> EligibilityDecision:
        now = now or datetime.now(UTC)
        decision = self.evaluate_operator(operator_id, now=now, lock=lock)
        reasons = decision.reasons

        aircraft = self.session.get(Aircraft, aircraft_id)
        if aircraft is None or aircraft.operator_id != operator_id:
            reasons.append(EligibilityReasonCode.AIRCRAFT_NOT_OPERATED_BY_OPERATOR)
            return EligibilityDecision(eligible=False, reasons=reasons)

        authorization = (
            self.authorizations.get_by_pair_for_update(operator_id, aircraft_id)
            if lock
            else self.authorizations.get_by_pair(operator_id, aircraft_id)
        )
        if authorization is None:
            reasons.append(EligibilityReasonCode.AIRCRAFT_NOT_AUTHORIZED)
        elif authorization.status is AircraftAuthorizationStatus.SUSPENDED:
            reasons.append(EligibilityReasonCode.AIRCRAFT_AUTHORIZATION_SUSPENDED)
        elif authorization.status is not AircraftAuthorizationStatus.APPROVED:
            reasons.append(EligibilityReasonCode.AIRCRAFT_NOT_AUTHORIZED)

        return EligibilityDecision(eligible=not reasons, reasons=reasons)

    @staticmethod
    def _has_current_evidence(items: Sequence[ComplianceEvidence], *, now: datetime) -> bool:
        return any(is_evidence_current(item.status, item.expiry_date, now=now) for item in items)

    @staticmethod
    def _evidence_reason(
        items: Sequence[ComplianceEvidence], evidence_type: EvidenceType, *, now: datetime
    ) -> EligibilityReasonCode:
        has_expired = any(
            item.status is EvidenceStatus.VERIFIED
            and item.expiry_date is not None
            and now >= item.expiry_date
            for item in items
        )
        if has_expired:
            return _EXPIRED_EVIDENCE_REASON[evidence_type]
        return _MISSING_EVIDENCE_REASON[evidence_type]
