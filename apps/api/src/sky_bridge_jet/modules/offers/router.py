from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.audience import (
    CustomerOfferResponse,
    InternalOfferResponse,
    OfferAudienceResponse,
)
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.customer_views import customer_offer_view
from sky_bridge_jet.modules.iam.dependencies import ActiveOrganization, CurrentPrincipal
from sky_bridge_jet.modules.iam.domain import Permission
from sky_bridge_jet.modules.offers.domain import OfferConflictError, effective_offer_status
from sky_bridge_jet.modules.offers.models import OperatorOffer
from sky_bridge_jet.modules.offers.schemas import (
    OperatorOfferCreate,
    OperatorOfferResponse,
    OperatorOfferUpdate,
)
from sky_bridge_jet.modules.offers.services import OperatorOfferService

router = APIRouter(tags=["operator-offers"])
DatabaseSession = Annotated[Session, Depends(get_db)]

# 404 not-found and 409 conflict use the safe envelope; the app documents 422
# and 500 globally.
_ERR = {"model": ErrorResponse}


def register_offer_exception_handlers(app: object) -> None:
    """Register the offer conflict handler using the shared safe error envelope."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(OfferConflictError)
    async def offer_conflict(request: Request, error: OfferConflictError) -> JSONResponse:
        response = JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": {"code": error.code, "message": str(error), "details": None}},
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id is not None:
            response.headers["X-Request-ID"] = correlation_id
        return response


def _to_response(offer: OperatorOffer) -> OperatorOfferResponse:
    now = datetime.now(UTC)
    return OperatorOfferResponse(
        id=offer.id,
        trip_request_id=offer.trip_request_id,
        operator_id=offer.operator_id,
        aircraft_id=offer.aircraft_id,
        status=effective_offer_status(offer.status, offer.valid_until, now=now),
        currency=offer.currency,
        operator_amount_minor=offer.operator_amount_minor,
        platform_fee_minor=offer.platform_fee_minor,
        tax_amount_minor=offer.tax_amount_minor,
        total_amount_minor=offer.total_amount_minor,
        valid_until=offer.valid_until,
        operator_legal_name=offer.operator_legal_name,
        aircraft_registration=offer.aircraft_registration,
        aircraft_manufacturer=offer.aircraft_manufacturer,
        aircraft_model=offer.aircraft_model,
        aircraft_category=offer.aircraft_category,
        operator_notes=offer.operator_notes,
        cancellation_policy=offer.cancellation_policy,
        included_services=offer.included_services,
        excluded_services=offer.excluded_services,
        created_at=offer.created_at,
        updated_at=offer.updated_at,
    )


def _write_hook(
    request: Request,
    principal: CurrentPrincipal,
    *,
    action: str,
    owner_operator_id: UUID | None,
    resource_reference: UUID | str,
) -> access.AuditHook | None:
    return access.platform_operator_exception_hook(
        principal,
        permission=Permission.OFFER_MANAGE,
        action=action,
        resource_type="offer",
        resource_reference=resource_reference,
        owner_operator_id=owner_operator_id,
        correlation_id=getattr(request.state, "correlation_id", None),
    )


@router.post(
    "/offers",
    response_model=OperatorOfferResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createOperatorOffer",
)
def create_offer(
    data: OperatorOfferCreate,
    request: Request,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> OperatorOfferResponse:
    # The offering operator is derived from the active OPERATOR org; a body operator_id
    # may only confirm that tenant. The service still enforces that the aircraft and
    # trip belong together (aircraft↔operator mismatch remains a 422 domain error).
    owner = access.resolve_write_operator(
        session,
        principal,
        permission=Permission.OFFER_MANAGE,
        body_operator_id=data.operator_id,
        requested_organization_id=active_organization,
    )
    session.rollback()
    scoped = data.model_copy(update={"operator_id": owner})
    hook = _write_hook(
        request,
        principal,
        action="createOperatorOffer",
        owner_operator_id=owner,
        resource_reference=owner,
    )
    return _to_response(OperatorOfferService(session).create(scoped, on_commit=hook))


@router.get(
    "/offers/{offer_id}",
    response_model=OperatorOfferResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getOperatorOffer",
)
def get_offer(
    offer_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> OperatorOfferResponse:
    offer = OperatorOfferService(session).get(offer_id)  # 404 if absent
    # The owning operator is a party to its own offer amounts; cross-operator → 404;
    # a platform viewer is allowed and audited.
    access.require_operator_access(principal, Permission.OFFER_READ, offer.operator_id)
    response = _to_response(offer)
    access.audit_operator_platform_read(
        session,
        principal,
        permission=Permission.OFFER_READ,
        action="getOperatorOffer",
        resource_type="offer",
        resource_reference=offer.id,
        owner_operator_id=offer.operator_id,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return response


@router.patch(
    "/offers/{offer_id}",
    response_model=OperatorOfferResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="updateDraftOperatorOffer",
)
def update_offer(
    offer_id: UUID,
    data: OperatorOfferUpdate,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> OperatorOfferResponse:
    owner = access.operator_of_offer(session, offer_id)
    access.require_operator_access(principal, Permission.OFFER_MANAGE, owner)
    session.rollback()
    hook = _write_hook(
        request,
        principal,
        action="updateDraftOperatorOffer",
        owner_operator_id=owner,
        resource_reference=offer_id,
    )
    return _to_response(OperatorOfferService(session).update_draft(offer_id, data, on_commit=hook))


@router.post(
    "/offers/{offer_id}/submit",
    response_model=OperatorOfferResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="submitOperatorOffer",
)
def submit_offer(
    offer_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> OperatorOfferResponse:
    owner = access.operator_of_offer(session, offer_id)
    access.require_operator_access(principal, Permission.OFFER_MANAGE, owner)
    session.rollback()
    hook = _write_hook(
        request,
        principal,
        action="submitOperatorOffer",
        owner_operator_id=owner,
        resource_reference=offer_id,
    )
    return _to_response(OperatorOfferService(session).submit(offer_id, on_commit=hook))


@router.post(
    "/offers/{offer_id}/withdraw",
    response_model=OperatorOfferResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="withdrawOperatorOffer",
)
def withdraw_offer(
    offer_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> OperatorOfferResponse:
    owner = access.operator_of_offer(session, offer_id)
    access.require_operator_access(principal, Permission.OFFER_MANAGE, owner)
    session.rollback()
    hook = _write_hook(
        request,
        principal,
        action="withdrawOperatorOffer",
        owner_operator_id=owner,
        resource_reference=offer_id,
    )
    return _to_response(OperatorOfferService(session).withdraw(offer_id, on_commit=hook))


@router.get(
    "/trip-requests/{trip_request_id}/offers",
    response_model=list[OfferAudienceResponse],
    responses={403: _ERR, 404: _ERR},
    operation_id="listTripRequestOffers",
)
def list_trip_offers(
    trip_request_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> list[OfferAudienceResponse]:
    # Phase 9.0.B: the owning customer now receives a customer-safe projection; a
    # platform viewer receives the full internal response (and is audited). Ownership
    # (trip → customer) is enforced for everyone; cross-tenant is concealed as 404.
    owner = access.owner_of_trip(session, trip_request_id)
    access.require_customer_access(principal, Permission.OFFER_READ, owner)
    access.audit_platform_read(
        session,
        principal,
        permission=Permission.OFFER_READ,
        action="listTripRequestOffers",
        resource_type="trip_request",
        resource_reference=trip_request_id,
        owner_customer_id=owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    offers = OperatorOfferService(session).list_for_trip(trip_request_id)
    if access.is_customer_view(principal, owner):
        return [
            CustomerOfferResponse.model_validate(customer_offer_view(offer)) for offer in offers
        ]
    return [InternalOfferResponse.model_validate(_to_response(offer)) for offer in offers]


@router.post(
    "/trip-requests/{trip_request_id}/offers/{offer_id}/select",
    response_model=OfferAudienceResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="selectOperatorOffer",
)
def select_offer(
    trip_request_id: UUID,
    offer_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> OfferAudienceResponse:
    owner = access.owner_of_trip(session, trip_request_id)
    access.require_customer_access(principal, Permission.TRIP_WRITE, owner)
    session.rollback()
    hook = access.platform_exception_hook(
        principal,
        permission=Permission.TRIP_WRITE,
        action="selectOperatorOffer",
        resource_type="offer",
        resource_reference=offer_id,
        owner_customer_id=owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    # The service enforces that the offer belongs to the trip and is still selectable.
    offer = OperatorOfferService(session).select(trip_request_id, offer_id, on_commit=hook)
    if access.is_customer_view(principal, owner):
        return CustomerOfferResponse.model_validate(customer_offer_view(offer))
    return InternalOfferResponse.model_validate(_to_response(offer))
