from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.flight_operations.schemas import OperatorFlightOperationView
from sky_bridge_jet.modules.flight_operations.services import FlightOperationService
from sky_bridge_jet.modules.iam.dependencies import ActiveOrganization, CurrentPrincipal
from sky_bridge_jet.modules.iam.domain import Permission

router = APIRouter(tags=["flight-operations"])
DatabaseSession = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/me/operator-operations",
    response_model=list[OperatorFlightOperationView],
    operation_id="listMyOperatorOperations",
)
def list_my_operator_operations(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = 20,
    offset: Offset = 0,
) -> list[OperatorFlightOperationView]:
    operator_id = access.active_operator_id(principal, active_organization)
    access.require_operator_access(principal, Permission.BOOKING_READ, operator_id)
    return FlightOperationService(session).list_for_operator(
        operator_id, limit=limit, offset=offset
    )


@router.get(
    "/me/operator-operations/{operation_id}",
    response_model=OperatorFlightOperationView,
    operation_id="getMyOperatorOperation",
)
def get_my_operator_operation(
    operation_id: UUID,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> OperatorFlightOperationView:
    operator_id = access.active_operator_id(principal, active_organization)
    access.require_operator_access(principal, Permission.BOOKING_READ, operator_id)
    return FlightOperationService(session).get_for_operator(operation_id, operator_id)
