from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sky_bridge_jet.modules.compliance.domain import (
    ActorType,
    AircraftAuthorizationStatus,
    ComplianceAction,
    ComplianceConflictError,
    ComplianceEntityType,
    EvidenceStatus,
    OperatorAdmissionStatus,
    ReviewReasonCode,
    require_review_actor,
    validate_admission_transition,
    validate_authorization_transition,
    validate_evidence_transition,
)
from sky_bridge_jet.modules.compliance.evaluator import ComplianceEvaluator, EligibilityDecision
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.compliance.repositories import (
    ComplianceAuditRepository,
    ComplianceEvidenceRepository,
    OperatorAdmissionRepository,
    OperatorAircraftAuthorizationRepository,
    PlatformAdmissionRecord,
    PlatformAuthorizationRecord,
    PlatformEvidenceRecord,
)
from sky_bridge_jet.modules.compliance.schemas import (
    AdmissionReviewAction,
    AdmissionReviewCommand,
    AuthorizationCreate,
    AuthorizationReviewAction,
    AuthorizationReviewCommand,
    EvidenceCreate,
    EvidenceReviewAction,
    EvidenceReviewCommand,
)
from sky_bridge_jet.modules.core_aviation.domain import DomainValidationError, ResourceNotFoundError
from sky_bridge_jet.modules.core_aviation.repositories import (
    AircraftRepository,
    OperatorRepository,
)

_ADMISSION_ACTIONS = {
    AdmissionReviewAction.BEGIN_REVIEW: (
        OperatorAdmissionStatus.UNDER_REVIEW,
        ComplianceAction.REVIEW_STARTED,
    ),
    AdmissionReviewAction.APPROVE: (OperatorAdmissionStatus.APPROVED, ComplianceAction.APPROVED),
    AdmissionReviewAction.REJECT: (OperatorAdmissionStatus.REJECTED, ComplianceAction.REJECTED),
    AdmissionReviewAction.SUSPEND: (OperatorAdmissionStatus.SUSPENDED, ComplianceAction.SUSPENDED),
    AdmissionReviewAction.RESTORE: (OperatorAdmissionStatus.APPROVED, ComplianceAction.RESTORED),
}
_AUTHORIZATION_ACTIONS = {
    AuthorizationReviewAction.BEGIN_REVIEW: (
        AircraftAuthorizationStatus.UNDER_REVIEW,
        ComplianceAction.REVIEW_STARTED,
    ),
    AuthorizationReviewAction.APPROVE: (
        AircraftAuthorizationStatus.APPROVED,
        ComplianceAction.APPROVED,
    ),
    AuthorizationReviewAction.REJECT: (
        AircraftAuthorizationStatus.REJECTED,
        ComplianceAction.REJECTED,
    ),
    AuthorizationReviewAction.SUSPEND: (
        AircraftAuthorizationStatus.SUSPENDED,
        ComplianceAction.SUSPENDED,
    ),
    AuthorizationReviewAction.RESTORE: (
        AircraftAuthorizationStatus.APPROVED,
        ComplianceAction.RESTORED,
    ),
}
_EVIDENCE_ACTIONS = {
    EvidenceReviewAction.BEGIN_REVIEW: (
        EvidenceStatus.UNDER_REVIEW,
        ComplianceAction.REVIEW_STARTED,
    ),
    EvidenceReviewAction.VERIFY: (EvidenceStatus.VERIFIED, ComplianceAction.VERIFIED),
    EvidenceReviewAction.REJECT: (EvidenceStatus.REJECTED, ComplianceAction.REJECTED),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_found(resource_name: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(f"{resource_name} was not found")


# Optional audit hook run inside the command transaction (Phase 9.0.A-2
# platform-exception auditing), so the audit commits atomically with the mutation.
OnCommit = Callable[[Session], None] | None


class ComplianceService:
    """Own compliance review workflows within one explicit transaction per write.

    Review decisions must be attributed to a human-authorized actor
    (PLATFORM_REVIEWER/PRODUCT_OWNER); authentication is deferred, so this is an
    audited abstraction a future authenticated reviewer replaces. Every material
    change appends to the audit trail; audit rows are never updated or deleted.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.admissions = OperatorAdmissionRepository(session)
        self.evidence = ComplianceEvidenceRepository(session)
        self.authorizations = OperatorAircraftAuthorizationRepository(session)
        self.audit = ComplianceAuditRepository(session)
        self.operators = OperatorRepository(session)
        self.aircraft = AircraftRepository(session)

    # -- Operator admission -------------------------------------------------

    def create_admission(
        self, operator_id: UUID, *, on_commit: OnCommit = None
    ) -> OperatorAdmission:
        with self.session.begin():
            if self.operators.get(operator_id) is None:
                raise _not_found("Operator")
            if self.admissions.get_by_operator(operator_id) is not None:
                raise ComplianceConflictError("An admission already exists for this operator")
            admission = self.admissions.add(
                OperatorAdmission(operator_id=operator_id, status=OperatorAdmissionStatus.DRAFT)
            )
            self.session.flush()
            self._audit(
                ComplianceEntityType.OPERATOR_ADMISSION,
                admission.id,
                ComplianceAction.CREATED,
                None,
                admission.status.value,
                ActorType.OPERATOR,
            )
            if on_commit is not None:
                on_commit(self.session)
            return admission

    def submit_admission(
        self, operator_id: UUID, *, on_commit: OnCommit = None
    ) -> OperatorAdmission:
        with self.session.begin():
            admission = self.admissions.get_by_operator_for_update(operator_id)
            if admission is None:
                raise _not_found("Operator admission")
            previous = admission.status
            validate_admission_transition(previous, OperatorAdmissionStatus.SUBMITTED)
            admission.status = OperatorAdmissionStatus.SUBMITTED
            admission.submitted_at = _utc_now()
            self._audit(
                ComplianceEntityType.OPERATOR_ADMISSION,
                admission.id,
                ComplianceAction.SUBMITTED,
                previous.value,
                admission.status.value,
                ActorType.OPERATOR,
            )
            self.session.flush()
            if on_commit is not None:
                on_commit(self.session)
            return admission

    def review_admission(
        self, operator_id: UUID, command: AdmissionReviewCommand
    ) -> OperatorAdmission:
        with self.session.begin():
            admission = self.admissions.get_by_operator_for_update(operator_id)
            if admission is None:
                raise _not_found("Operator admission")
            require_review_actor(command.actor_type)
            target, action = _ADMISSION_ACTIONS[command.action]
            previous = admission.status
            validate_admission_transition(previous, target)
            admission.status = target
            admission.reviewed_at = _utc_now()
            admission.reason_code = command.reason_code
            admission.review_note = command.note
            self._audit(
                ComplianceEntityType.OPERATOR_ADMISSION,
                admission.id,
                action,
                previous.value,
                target.value,
                command.actor_type,
                command.actor_reference,
                command.reason_code,
                command.note,
            )
            self.session.flush()
            return admission

    def get_admission(self, operator_id: UUID) -> OperatorAdmission:
        admission = self.admissions.get_by_operator(operator_id)
        if admission is None:
            raise _not_found("Operator admission")
        return admission

    def get_platform_admission(self, admission_id: UUID) -> PlatformAdmissionRecord:
        admission = self.admissions.get(admission_id)
        if admission is None:
            raise _not_found("Operator admission")
        operator = self.operators.get(admission.operator_id)
        if operator is None:
            raise _not_found("Operator")
        return PlatformAdmissionRecord(
            admission, operator.legal_name, operator.trading_name, operator.country_code
        )

    def list_platform_admissions(
        self, *, status: OperatorAdmissionStatus | None, limit: int, offset: int
    ) -> Sequence[PlatformAdmissionRecord]:
        return self.admissions.list_platform_review(status=status, limit=limit, offset=offset)

    # -- Evidence -----------------------------------------------------------

    def submit_evidence(
        self, operator_id: UUID, data: EvidenceCreate, *, on_commit: OnCommit = None
    ) -> ComplianceEvidence:
        with self.session.begin():
            if self.operators.get(operator_id) is None:
                raise _not_found("Operator")
            if data.aircraft_id is not None:
                aircraft = self.aircraft.get(data.aircraft_id)
                if aircraft is None:
                    raise _not_found("Aircraft")
                if aircraft.operator_id != operator_id:
                    raise DomainValidationError("Aircraft does not belong to the operator")

            superseded = None
            if data.supersedes_evidence_id is not None:
                superseded = self.evidence.get_for_update(data.supersedes_evidence_id)
                if superseded is None or superseded.operator_id != operator_id:
                    raise _not_found("Superseded evidence")
                validate_evidence_transition(superseded.status, EvidenceStatus.SUPERSEDED)

            evidence = self.evidence.add(
                ComplianceEvidence(
                    operator_id=operator_id,
                    aircraft_id=data.aircraft_id,
                    evidence_type=data.evidence_type,
                    status=EvidenceStatus.SUBMITTED,
                    authority_basis=data.authority_basis,
                    reference_number=data.reference_number,
                    issuing_authority=data.issuing_authority,
                    jurisdiction=data.jurisdiction,
                    insurer_name=data.insurer_name,
                    storage_object_reference=data.storage_object_reference,
                    effective_date=data.effective_date,
                    expiry_date=data.expiry_date,
                    submitted_at=_utc_now(),
                )
            )
            self.session.flush()

            if superseded is not None:
                previous = superseded.status
                superseded.status = EvidenceStatus.SUPERSEDED
                superseded.superseded_by_id = evidence.id
                self._audit(
                    ComplianceEntityType.COMPLIANCE_EVIDENCE,
                    superseded.id,
                    ComplianceAction.SUPERSEDED,
                    previous.value,
                    EvidenceStatus.SUPERSEDED.value,
                    ActorType.OPERATOR,
                )

            self._audit(
                ComplianceEntityType.COMPLIANCE_EVIDENCE,
                evidence.id,
                ComplianceAction.SUBMITTED,
                None,
                evidence.status.value,
                ActorType.OPERATOR,
            )
            self.session.flush()
            if on_commit is not None:
                on_commit(self.session)
            return evidence

    def review_evidence(
        self, evidence_id: UUID, command: EvidenceReviewCommand
    ) -> ComplianceEvidence:
        with self.session.begin():
            evidence = self.evidence.get_for_update(evidence_id)
            if evidence is None:
                raise _not_found("Evidence")
            require_review_actor(command.actor_type)
            target, action = _EVIDENCE_ACTIONS[command.action]
            previous = evidence.status
            validate_evidence_transition(previous, target)
            evidence.status = target
            evidence.reviewed_at = _utc_now()
            evidence.review_reason_code = command.reason_code
            evidence.review_note = command.note
            self._audit(
                ComplianceEntityType.COMPLIANCE_EVIDENCE,
                evidence.id,
                action,
                previous.value,
                target.value,
                command.actor_type,
                command.actor_reference,
                command.reason_code,
                command.note,
            )
            self.session.flush()
            return evidence

    def get_evidence(self, evidence_id: UUID) -> ComplianceEvidence:
        evidence = self.evidence.get(evidence_id)
        if evidence is None:
            raise _not_found("Evidence")
        return evidence

    def get_platform_evidence(self, evidence_id: UUID) -> PlatformEvidenceRecord:
        evidence = self.get_evidence(evidence_id)
        operator = self.operators.get(evidence.operator_id)
        if operator is None:
            raise _not_found("Operator")
        aircraft = self.aircraft.get(evidence.aircraft_id) if evidence.aircraft_id else None
        return PlatformEvidenceRecord(
            evidence,
            operator.legal_name,
            operator.trading_name,
            aircraft.registration if aircraft is not None else None,
        )

    def list_platform_evidence(
        self, *, status: EvidenceStatus | None, limit: int, offset: int
    ) -> Sequence[PlatformEvidenceRecord]:
        return self.evidence.list_platform_review(status=status, limit=limit, offset=offset)

    def list_evidence(self, operator_id: UUID) -> list[ComplianceEvidence]:
        if self.operators.get(operator_id) is None:
            raise _not_found("Operator")
        return list(self.evidence.list_for_operator(operator_id))

    # -- Operator/aircraft authorization ------------------------------------

    def create_authorization(
        self,
        operator_id: UUID,
        aircraft_id: UUID,
        data: AuthorizationCreate,
        *,
        on_commit: OnCommit = None,
    ) -> OperatorAircraftAuthorization:
        with self.session.begin():
            if self.operators.get(operator_id) is None:
                raise _not_found("Operator")
            aircraft = self.aircraft.get(aircraft_id)
            if aircraft is None:
                raise _not_found("Aircraft")
            if aircraft.operator_id != operator_id:
                raise DomainValidationError("Aircraft does not belong to the operator")
            if self.authorizations.get_by_pair(operator_id, aircraft_id) is not None:
                raise ComplianceConflictError(
                    "An authorization already exists for this operator and aircraft"
                )
            authorization = self.authorizations.add(
                OperatorAircraftAuthorization(
                    operator_id=operator_id,
                    aircraft_id=aircraft_id,
                    status=AircraftAuthorizationStatus.DRAFT,
                    authority_basis=data.authority_basis,
                )
            )
            self.session.flush()
            self._audit(
                ComplianceEntityType.AIRCRAFT_AUTHORIZATION,
                authorization.id,
                ComplianceAction.CREATED,
                None,
                authorization.status.value,
                ActorType.OPERATOR,
            )
            if on_commit is not None:
                on_commit(self.session)
            return authorization

    def submit_authorization(
        self, operator_id: UUID, aircraft_id: UUID, *, on_commit: OnCommit = None
    ) -> OperatorAircraftAuthorization:
        with self.session.begin():
            authorization = self.authorizations.get_by_pair_for_update(operator_id, aircraft_id)
            if authorization is None:
                raise _not_found("Aircraft authorization")
            previous = authorization.status
            validate_authorization_transition(previous, AircraftAuthorizationStatus.SUBMITTED)
            authorization.status = AircraftAuthorizationStatus.SUBMITTED
            authorization.submitted_at = _utc_now()
            self._audit(
                ComplianceEntityType.AIRCRAFT_AUTHORIZATION,
                authorization.id,
                ComplianceAction.SUBMITTED,
                previous.value,
                authorization.status.value,
                ActorType.OPERATOR,
            )
            self.session.flush()
            if on_commit is not None:
                on_commit(self.session)
            return authorization

    def review_authorization(
        self, operator_id: UUID, aircraft_id: UUID, command: AuthorizationReviewCommand
    ) -> OperatorAircraftAuthorization:
        with self.session.begin():
            authorization = self.authorizations.get_by_pair_for_update(operator_id, aircraft_id)
            if authorization is None:
                raise _not_found("Aircraft authorization")
            require_review_actor(command.actor_type)
            target, action = _AUTHORIZATION_ACTIONS[command.action]
            previous = authorization.status
            validate_authorization_transition(previous, target)
            authorization.status = target
            authorization.reviewed_at = _utc_now()
            authorization.reason_code = command.reason_code
            authorization.review_note = command.note
            self._audit(
                ComplianceEntityType.AIRCRAFT_AUTHORIZATION,
                authorization.id,
                action,
                previous.value,
                target.value,
                command.actor_type,
                command.actor_reference,
                command.reason_code,
                command.note,
            )
            self.session.flush()
            return authorization

    def get_authorization(
        self, operator_id: UUID, aircraft_id: UUID
    ) -> OperatorAircraftAuthorization:
        authorization = self.authorizations.get_by_pair(operator_id, aircraft_id)
        if authorization is None:
            raise _not_found("Aircraft authorization")
        return authorization

    def get_platform_authorization(self, authorization_id: UUID) -> PlatformAuthorizationRecord:
        authorization = self.authorizations.get(authorization_id)
        if authorization is None:
            raise _not_found("Aircraft authorization")
        operator = self.operators.get(authorization.operator_id)
        aircraft = self.aircraft.get(authorization.aircraft_id)
        if operator is None or aircraft is None:
            raise _not_found("Aircraft authorization")
        return PlatformAuthorizationRecord(
            authorization,
            operator.legal_name,
            operator.trading_name,
            aircraft.registration,
            aircraft.manufacturer,
            aircraft.model,
        )

    def list_platform_authorizations(
        self, *, status: AircraftAuthorizationStatus | None, limit: int, offset: int
    ) -> Sequence[PlatformAuthorizationRecord]:
        return self.authorizations.list_platform_review(status=status, limit=limit, offset=offset)

    # -- Eligibility (reads) ------------------------------------------------

    def operator_eligibility(self, operator_id: UUID) -> EligibilityDecision:
        if self.operators.get(operator_id) is None:
            raise _not_found("Operator")
        return ComplianceEvaluator(self.session).evaluate_operator(operator_id)

    def operator_readiness(
        self, operator_id: UUID
    ) -> tuple[OperatorAdmission | None, EligibilityDecision]:
        """Return admission facts and the canonical marketplace decision, read-only."""
        if self.operators.get(operator_id) is None:
            raise _not_found("Operator")
        admission = self.admissions.get_by_operator(operator_id)
        decision = ComplianceEvaluator(self.session).evaluate_operator(operator_id)
        return admission, decision

    def operator_aircraft_eligibility(
        self, operator_id: UUID, aircraft_id: UUID
    ) -> EligibilityDecision:
        if self.operators.get(operator_id) is None:
            raise _not_found("Operator")
        if self.aircraft.get(aircraft_id) is None:
            raise _not_found("Aircraft")
        return ComplianceEvaluator(self.session).evaluate_operator_aircraft(
            operator_id, aircraft_id
        )

    # -- Audit --------------------------------------------------------------

    def list_audit_events(
        self, entity_type: ComplianceEntityType, entity_id: UUID, *, limit: int | None = None
    ) -> Sequence[ComplianceAuditEvent]:
        return self.audit.list_for_entity(entity_type, entity_id, limit=limit)

    def _audit(
        self,
        entity_type: ComplianceEntityType,
        entity_id: UUID,
        action: ComplianceAction,
        previous_status: str | None,
        new_status: str | None,
        actor_type: ActorType,
        actor_reference: str | None = None,
        reason_code: ReviewReasonCode | None = None,
        note: str | None = None,
    ) -> None:
        self.audit.add(
            ComplianceAuditEvent(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                previous_status=previous_status,
                new_status=new_status,
                actor_type=actor_type,
                actor_reference=actor_reference,
                reason_code=reason_code,
                note=note,
            )
        )
