from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.iam.dependencies import (
    ActiveOrganization,
    CurrentPrincipal,
    DatabaseSession,
)
from sky_bridge_jet.modules.iam.domain import Permission
from sky_bridge_jet.modules.pilot_governance.domain import (
    PilotAccessDeniedError,
    PilotGovernanceConflictError,
    PilotGovernanceNotFoundError,
    PilotParticipantStatus,
    PilotParticipantType,
)
from sky_bridge_jet.modules.pilot_governance.models import PilotParticipant
from sky_bridge_jet.modules.pilot_governance.schemas import (
    ParticipantCommand,
    ParticipantCreate,
    ParticipantResponse,
    PilotAuditResponse,
    PilotStateCommand,
    PilotStateResponse,
)
from sky_bridge_jet.modules.pilot_governance.services import PilotGovernanceService

router = APIRouter(prefix="/platform/pilot", tags=["pilot-governance"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def register_pilot_exception_handlers(app: object) -> None:
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    def response(request: Request, code: int, error: Exception, error_code: str) -> JSONResponse:
        result = JSONResponse(
            status_code=code,
            content={"error": {"code": error_code, "message": str(error), "details": None}},
        )
        correlation = getattr(request.state, "correlation_id", None)
        if correlation:
            result.headers["X-Request-ID"] = correlation
        return result

    @app.exception_handler(PilotAccessDeniedError)
    async def denied(request: Request, error: PilotAccessDeniedError) -> JSONResponse:
        return response(request, 403, error, error.code)

    @app.exception_handler(PilotGovernanceConflictError)
    async def conflict(request: Request, error: PilotGovernanceConflictError) -> JSONResponse:
        return response(request, 409, error, error.code)

    @app.exception_handler(PilotGovernanceNotFoundError)
    async def missing(request: Request, error: PilotGovernanceNotFoundError) -> JSONResponse:
        return response(request, 404, error, error.code)


def _participant(row: tuple[PilotParticipant, str]) -> ParticipantResponse:
    participant, name = row
    return ParticipantResponse(
        id=participant.id,
        organization_id=participant.organization_id,
        organization_name=name,
        participant_type=participant.participant_type,
        status=participant.status,
        version=participant.version,
        created_at=participant.created_at,
        updated_at=participant.updated_at,
    )


@router.get("/state", response_model=PilotStateResponse)
def get_pilot_state(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> PilotStateResponse:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_READ)
    return PilotStateResponse.model_validate(PilotGovernanceService(session).state())


@router.post("/state", response_model=PilotStateResponse)
def update_pilot_state(
    data: PilotStateCommand,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> PilotStateResponse:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_MANAGE)
    return PilotStateResponse.model_validate(
        PilotGovernanceService(session).update_state(
            actor=principal.user_id,
            mode=data.mode,
            payment_enabled=data.payment_initiation_enabled,
            expected_version=data.expected_version,
            reason=data.reason,
        )
    )


@router.get("/participants", response_model=list[ParticipantResponse])
def list_participants(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = 20,
    offset: Offset = 0,
    participant_status: PilotParticipantStatus | None = None,
    participant_type: PilotParticipantType | None = None,
) -> list[ParticipantResponse]:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_READ)
    return [
        _participant(row)
        for row in PilotGovernanceService(session).list_participants(
            limit=limit, offset=offset, status=participant_status, kind=participant_type
        )
    ]


@router.post(
    "/participants",
    response_model=ParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_participant(
    data: ParticipantCreate,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> ParticipantResponse:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_MANAGE)
    service = PilotGovernanceService(session)
    participant = service.create_participant(
        actor=principal.user_id, organization_id=data.organization_id, reason=data.reason
    )
    return _participant(service.get_participant(participant.id))


@router.get("/participants/{participant_id}", response_model=ParticipantResponse)
def get_participant(
    participant_id: UUID,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> ParticipantResponse:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_READ)
    return _participant(PilotGovernanceService(session).get_participant(participant_id))


@router.post(
    "/participants/{participant_id}/status",
    response_model=ParticipantResponse,
)
def update_participant(
    participant_id: UUID,
    data: ParticipantCommand,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> ParticipantResponse:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_MANAGE)
    service = PilotGovernanceService(session)
    participant = service.mutate_participant(
        participant_id,
        actor=principal.user_id,
        status=data.status,
        expected_version=data.expected_version,
        reason=data.reason,
    )
    return _participant(service.get_participant(participant.id))


@router.get("/audits", response_model=list[PilotAuditResponse])
def list_audits(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[PilotAuditResponse]:
    access.active_platform_organization_id(principal, active_organization, Permission.PILOT_READ)
    return [
        PilotAuditResponse.model_validate(item)
        for item in PilotGovernanceService(session).list_audits(limit=limit, offset=offset)
    ]
