from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.compliance.domain import (
    ComplianceConflictError,
    ComplianceEntityType,
    ComplianceGateError,
    effective_evidence_status,
)
from sky_bridge_jet.modules.compliance.evaluator import EligibilityDecision
from sky_bridge_jet.modules.compliance.models import (
    ComplianceAuditEvent,
    ComplianceEvidence,
    OperatorAdmission,
    OperatorAircraftAuthorization,
)
from sky_bridge_jet.modules.compliance.schemas import (
    AdmissionReviewCommand,
    AuditEventResponse,
    AuthorizationCreate,
    AuthorizationResponse,
    AuthorizationReviewCommand,
    EvidenceCreate,
    EvidenceResponse,
    EvidenceReviewCommand,
    OperatorAdmissionResponse,
    OperatorAircraftEligibilityResponse,
    OperatorEligibilityResponse,
)
from sky_bridge_jet.modules.compliance.services import ComplianceService
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.iam.dependencies import require_permission
from sky_bridge_jet.modules.iam.domain import Permission

router = APIRouter(tags=["compliance"])
DatabaseSession = Annotated[Session, Depends(get_db)]

_ERR = {"model": ErrorResponse}
# Platform review is high-consequence: only an authenticated principal holding the
# compliance-review permission may decide. Operator/customer roles never hold it, so
# an operator can never approve its own admission (Phase 8, ADR-037).
_REQUIRE_COMPLIANCE_REVIEW = require_permission(Permission.COMPLIANCE_REVIEW)


def register_compliance_exception_handlers(app: object) -> None:
    """Register the compliance conflict handler using the shared safe error envelope."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(ComplianceConflictError)
    async def compliance_conflict(request: Request, error: ComplianceConflictError) -> JSONResponse:
        details: list[dict[str, object]] | None = None
        if isinstance(error, ComplianceGateError):
            details = [{"reason": reason.value} for reason in error.reasons]
        response = JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": {"code": error.code, "message": str(error), "details": details}},
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id is not None:
            response.headers["X-Request-ID"] = correlation_id
        return response


def _admission(admission: OperatorAdmission) -> OperatorAdmissionResponse:
    return OperatorAdmissionResponse.model_validate(admission)


def _authorization(authorization: OperatorAircraftAuthorization) -> AuthorizationResponse:
    return AuthorizationResponse.model_validate(authorization)


def _audit_event(event: ComplianceAuditEvent) -> AuditEventResponse:
    return AuditEventResponse.model_validate(event)


def _evidence(evidence: ComplianceEvidence) -> EvidenceResponse:
    now = datetime.now(UTC)
    return EvidenceResponse(
        id=evidence.id,
        operator_id=evidence.operator_id,
        aircraft_id=evidence.aircraft_id,
        evidence_type=evidence.evidence_type,
        status=evidence.status,
        effective_status=effective_evidence_status(evidence.status, evidence.expiry_date, now=now),
        authority_basis=evidence.authority_basis,
        reference_number=evidence.reference_number,
        issuing_authority=evidence.issuing_authority,
        jurisdiction=evidence.jurisdiction,
        insurer_name=evidence.insurer_name,
        storage_object_reference=evidence.storage_object_reference,
        effective_date=evidence.effective_date,
        expiry_date=evidence.expiry_date,
        submitted_at=evidence.submitted_at,
        reviewed_at=evidence.reviewed_at,
        review_reason_code=evidence.review_reason_code,
        review_note=evidence.review_note,
        superseded_by_id=evidence.superseded_by_id,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


def _operator_eligibility(
    operator_id: UUID, decision: EligibilityDecision
) -> OperatorEligibilityResponse:
    return OperatorEligibilityResponse(
        operator_id=operator_id, eligible=decision.eligible, reasons=decision.reasons
    )


# -- Operator admission -----------------------------------------------------


@router.post(
    "/operators/{operator_id}/admission",
    response_model=OperatorAdmissionResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createOperatorAdmission",
)
def create_admission(operator_id: UUID, session: DatabaseSession) -> OperatorAdmissionResponse:
    return _admission(ComplianceService(session).create_admission(operator_id))


@router.get(
    "/operators/{operator_id}/admission",
    response_model=OperatorAdmissionResponse,
    responses={404: _ERR},
    operation_id="getOperatorAdmission",
)
def get_admission(operator_id: UUID, session: DatabaseSession) -> OperatorAdmissionResponse:
    return _admission(ComplianceService(session).get_admission(operator_id))


@router.post(
    "/operators/{operator_id}/admission/submit",
    response_model=OperatorAdmissionResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="submitOperatorAdmission",
)
def submit_admission(operator_id: UUID, session: DatabaseSession) -> OperatorAdmissionResponse:
    return _admission(ComplianceService(session).submit_admission(operator_id))


@router.post(
    "/operators/{operator_id}/admission/review",
    dependencies=[_REQUIRE_COMPLIANCE_REVIEW],
    response_model=OperatorAdmissionResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="reviewOperatorAdmission",
)
def review_admission(
    operator_id: UUID, command: AdmissionReviewCommand, session: DatabaseSession
) -> OperatorAdmissionResponse:
    return _admission(ComplianceService(session).review_admission(operator_id, command))


@router.get(
    "/operators/{operator_id}/admission/audit-events",
    response_model=list[AuditEventResponse],
    responses={404: _ERR},
    operation_id="listOperatorAdmissionAuditEvents",
)
def list_admission_audit(operator_id: UUID, session: DatabaseSession) -> list[AuditEventResponse]:
    service = ComplianceService(session)
    admission = service.get_admission(operator_id)
    events = service.list_audit_events(ComplianceEntityType.OPERATOR_ADMISSION, admission.id)
    return [_audit_event(event) for event in events]


# -- Evidence ---------------------------------------------------------------


@router.post(
    "/operators/{operator_id}/evidence",
    response_model=EvidenceResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="submitComplianceEvidence",
)
def submit_evidence(
    operator_id: UUID, data: EvidenceCreate, session: DatabaseSession
) -> EvidenceResponse:
    return _evidence(ComplianceService(session).submit_evidence(operator_id, data))


@router.get(
    "/operators/{operator_id}/evidence",
    response_model=list[EvidenceResponse],
    responses={404: _ERR},
    operation_id="listComplianceEvidence",
)
def list_evidence(operator_id: UUID, session: DatabaseSession) -> list[EvidenceResponse]:
    return [_evidence(item) for item in ComplianceService(session).list_evidence(operator_id)]


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceResponse,
    responses={404: _ERR},
    operation_id="getComplianceEvidence",
)
def get_evidence(evidence_id: UUID, session: DatabaseSession) -> EvidenceResponse:
    return _evidence(ComplianceService(session).get_evidence(evidence_id))


@router.post(
    "/evidence/{evidence_id}/review",
    dependencies=[_REQUIRE_COMPLIANCE_REVIEW],
    response_model=EvidenceResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="reviewComplianceEvidence",
)
def review_evidence(
    evidence_id: UUID, command: EvidenceReviewCommand, session: DatabaseSession
) -> EvidenceResponse:
    return _evidence(ComplianceService(session).review_evidence(evidence_id, command))


@router.get(
    "/evidence/{evidence_id}/audit-events",
    response_model=list[AuditEventResponse],
    responses={404: _ERR},
    operation_id="listComplianceEvidenceAuditEvents",
)
def list_evidence_audit(evidence_id: UUID, session: DatabaseSession) -> list[AuditEventResponse]:
    service = ComplianceService(session)
    evidence = service.get_evidence(evidence_id)
    events = service.list_audit_events(ComplianceEntityType.COMPLIANCE_EVIDENCE, evidence.id)
    return [_audit_event(event) for event in events]


# -- Operator/aircraft authorization ----------------------------------------


@router.post(
    "/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
    response_model=AuthorizationResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createAircraftAuthorization",
)
def create_authorization(
    operator_id: UUID, aircraft_id: UUID, data: AuthorizationCreate, session: DatabaseSession
) -> AuthorizationResponse:
    return _authorization(
        ComplianceService(session).create_authorization(operator_id, aircraft_id, data)
    )


@router.get(
    "/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
    response_model=AuthorizationResponse,
    responses={404: _ERR},
    operation_id="getAircraftAuthorization",
)
def get_authorization(
    operator_id: UUID, aircraft_id: UUID, session: DatabaseSession
) -> AuthorizationResponse:
    return _authorization(ComplianceService(session).get_authorization(operator_id, aircraft_id))


@router.post(
    "/operators/{operator_id}/aircraft/{aircraft_id}/authorization/submit",
    response_model=AuthorizationResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="submitAircraftAuthorization",
)
def submit_authorization(
    operator_id: UUID, aircraft_id: UUID, session: DatabaseSession
) -> AuthorizationResponse:
    return _authorization(ComplianceService(session).submit_authorization(operator_id, aircraft_id))


@router.post(
    "/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review",
    dependencies=[_REQUIRE_COMPLIANCE_REVIEW],
    response_model=AuthorizationResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="reviewAircraftAuthorization",
)
def review_authorization(
    operator_id: UUID,
    aircraft_id: UUID,
    command: AuthorizationReviewCommand,
    session: DatabaseSession,
) -> AuthorizationResponse:
    return _authorization(
        ComplianceService(session).review_authorization(operator_id, aircraft_id, command)
    )


# -- Eligibility ------------------------------------------------------------


@router.get(
    "/operators/{operator_id}/eligibility",
    response_model=OperatorEligibilityResponse,
    responses={404: _ERR},
    operation_id="getOperatorEligibility",
)
def operator_eligibility(
    operator_id: UUID, session: DatabaseSession
) -> OperatorEligibilityResponse:
    decision = ComplianceService(session).operator_eligibility(operator_id)
    return _operator_eligibility(operator_id, decision)


@router.get(
    "/operators/{operator_id}/aircraft/{aircraft_id}/eligibility",
    response_model=OperatorAircraftEligibilityResponse,
    responses={404: _ERR},
    operation_id="getOperatorAircraftEligibility",
)
def operator_aircraft_eligibility(
    operator_id: UUID, aircraft_id: UUID, session: DatabaseSession
) -> OperatorAircraftEligibilityResponse:
    decision = ComplianceService(session).operator_aircraft_eligibility(operator_id, aircraft_id)
    return OperatorAircraftEligibilityResponse(
        operator_id=operator_id,
        aircraft_id=aircraft_id,
        eligible=decision.eligible,
        reasons=decision.reasons,
    )
