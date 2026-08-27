from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.audience import (
    BookingAudienceResponse,
    CustomerBookingResponse,
    InternalBookingResponse,
)
from sky_bridge_jet.modules.bookings.domain import BookingConflictError, BookingStatus
from sky_bridge_jet.modules.bookings.schemas import (
    BookingCancel,
    BookingConfirm,
    BookingCreate,
    BookingReject,
    BookingResponse,
    OperatorBookingReadView,
    OperatorBookingView,
)
from sky_bridge_jet.modules.bookings.services import BookingService
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.customer_views import customer_booking_view
from sky_bridge_jet.modules.iam.dependencies import ActiveOrganization, CurrentPrincipal
from sky_bridge_jet.modules.iam.domain import OrganizationType, Permission

router = APIRouter(tags=["bookings"])
DatabaseSession = Annotated[Session, Depends(get_db)]

# 404 not-found and 409 conflict use the safe envelope; the app documents 422
# and 500 globally.
_ERR = {"model": ErrorResponse}
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def register_booking_exception_handlers(app: object) -> None:
    """Register the booking conflict handler using the shared safe error envelope."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(BookingConflictError)
    async def booking_conflict(request: Request, error: BookingConflictError) -> JSONResponse:
        response = JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": {"code": error.code, "message": str(error), "details": None}},
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id is not None:
            response.headers["X-Request-ID"] = correlation_id
        return response


@router.post(
    "/bookings",
    response_model=BookingAudienceResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createBooking",
)
def create_booking(
    data: BookingCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> BookingAudienceResponse:
    # Ownership is derived from the referenced trip; owner ids are never trusted from
    # the body. The service enforces the offer→trip relationship and lifecycle. The
    # owning customer receives a customer-safe view (Phase 9.0.B); platform → full.
    owner = access.owner_of_trip(session, data.trip_request_id)
    access.require_customer_access(principal, Permission.TRIP_WRITE, owner)
    session.rollback()
    hook = access.platform_exception_hook(
        principal,
        permission=Permission.TRIP_WRITE,
        action="createBooking",
        resource_type="trip_request",
        resource_reference=data.trip_request_id,
        owner_customer_id=owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    booking = BookingService(session).create(data, on_commit=hook)
    if access.is_customer_view(principal, owner):
        return CustomerBookingResponse.model_validate(customer_booking_view(booking))
    return InternalBookingResponse.model_validate(booking)


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingAudienceResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getBooking",
)
def get_booking(
    booking_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> BookingAudienceResponse:
    # The owning operator (Booking.operator_id) is a party and receives the full
    # response; the owning customer receives a customer-safe view (Phase 9.0.B); a
    # platform viewer receives the full response (and is audited); cross-tenant → 404.
    owner_customer = access.owner_of_booking(session, booking_id)
    owner_operator = access.operator_of_booking(session, booking_id)
    access.require_booking_read_access(
        principal, owner_customer_id=owner_customer, owner_operator_id=owner_operator
    )
    access.audit_platform_read(
        session,
        principal,
        permission=Permission.BOOKING_READ,
        action="getBooking",
        resource_type="booking",
        resource_reference=booking_id,
        owner_customer_id=owner_customer,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    booking = BookingService(session).get(booking_id)
    if access.is_customer_view(principal, owner_customer):
        return CustomerBookingResponse.model_validate(customer_booking_view(booking))
    return InternalBookingResponse.model_validate(booking)


@router.get(
    "/trip-requests/{trip_request_id}/booking",
    response_model=BookingAudienceResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getTripRequestBooking",
)
def get_trip_booking(
    trip_request_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> BookingAudienceResponse:
    owner = access.owner_of_trip(session, trip_request_id)
    access.require_customer_access(principal, Permission.BOOKING_READ, owner)
    access.audit_platform_read(
        session,
        principal,
        permission=Permission.BOOKING_READ,
        action="getTripRequestBooking",
        resource_type="trip_request",
        resource_reference=trip_request_id,
        owner_customer_id=owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    booking = BookingService(session).get_for_trip(trip_request_id)
    if access.is_customer_view(principal, owner):
        return CustomerBookingResponse.model_validate(customer_booking_view(booking))
    return InternalBookingResponse.model_validate(booking)


@router.get(
    "/me/operator-bookings",
    response_model=list[OperatorBookingView],
    responses={403: _ERR},
    operation_id="listMyOperatorBookings",
)
def list_my_operator_bookings(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[OperatorBookingView]:
    operator_id = access.active_operator_id(principal, active_organization)
    access.require_operator_access(principal, Permission.BOOKING_READ, operator_id)
    return BookingService(session).list_pending_for_operator(
        operator_id, limit=limit, offset=offset
    )


@router.get(
    "/me/operator-bookings/history",
    response_model=list[OperatorBookingReadView],
    responses={403: _ERR},
    operation_id="listMyOperatorBookingHistory",
)
def list_my_operator_booking_history(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = 20,
    offset: Offset = 0,
    booking_status: Annotated[BookingStatus | None, Query(alias="status")] = None,
) -> list[OperatorBookingReadView]:
    operator_id = access.active_operator_id(principal, active_organization)
    access.require_operator_access(principal, Permission.BOOKING_READ, operator_id)
    return BookingService(session).list_history_for_operator(
        operator_id,
        booking_status=booking_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/me/operator-bookings/{booking_id}",
    response_model=OperatorBookingReadView,
    responses={403: _ERR, 404: _ERR},
    operation_id="getMyOperatorBooking",
)
def get_my_operator_booking(
    booking_id: UUID,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> OperatorBookingReadView:
    operator_id = access.active_operator_id(principal, active_organization)
    access.require_operator_access(principal, Permission.BOOKING_READ, operator_id)
    return BookingService(session).get_for_operator(booking_id, operator_id)


@router.post(
    "/bookings/{booking_id}/confirm",
    response_model=BookingResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="confirmBooking",
)
def confirm_booking(
    booking_id: UUID,
    data: BookingConfirm,
    request: Request,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> BookingResponse:
    # Operator ownership is resolved server-side (Booking.operator_id); the body
    # operator_id never controls authorization (the service still validates it against
    # the booking's operator, preserving the operator-mismatch domain check).
    owner_operator = access.operator_of_booking(session, booking_id)
    is_operator = any(
        membership.organization_type is OrganizationType.OPERATOR
        for membership in principal.memberships
    )
    if is_operator:
        acting_operator = access.active_operator_id(principal, active_organization)
        access.require_operator_access(principal, Permission.BOOKING_DECIDE, acting_operator)
    else:
        access.require_operator_access(principal, Permission.BOOKING_DECIDE, owner_operator)
        assert owner_operator is not None
        acting_operator = owner_operator
    if acting_operator != owner_operator:
        access.require_operator_access(principal, Permission.BOOKING_DECIDE, owner_operator)
    scoped = (
        data
        if data.operator_id is not None
        else data.model_copy(update={"operator_id": acting_operator})
    )
    session.rollback()
    hook = access.platform_operator_exception_hook(
        principal,
        permission=Permission.BOOKING_DECIDE,
        action="confirmBooking",
        resource_type="booking",
        resource_reference=booking_id,
        owner_operator_id=owner_operator,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return BookingResponse.model_validate(
        BookingService(session).confirm(booking_id, scoped, on_commit=hook)
    )


@router.post(
    "/bookings/{booking_id}/reject",
    response_model=BookingResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="rejectBooking",
)
def reject_booking(
    booking_id: UUID,
    data: BookingReject,
    request: Request,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> BookingResponse:
    owner_operator = access.operator_of_booking(session, booking_id)
    is_operator = any(
        membership.organization_type is OrganizationType.OPERATOR
        for membership in principal.memberships
    )
    if is_operator:
        acting_operator = access.active_operator_id(principal, active_organization)
        access.require_operator_access(principal, Permission.BOOKING_DECIDE, acting_operator)
    else:
        access.require_operator_access(principal, Permission.BOOKING_DECIDE, owner_operator)
        assert owner_operator is not None
        acting_operator = owner_operator
    if acting_operator != owner_operator:
        access.require_operator_access(principal, Permission.BOOKING_DECIDE, owner_operator)
    scoped = (
        data
        if data.operator_id is not None
        else data.model_copy(update={"operator_id": acting_operator})
    )
    session.rollback()
    hook = access.platform_operator_exception_hook(
        principal,
        permission=Permission.BOOKING_DECIDE,
        action="rejectBooking",
        resource_type="booking",
        resource_reference=booking_id,
        owner_operator_id=owner_operator,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return BookingResponse.model_validate(
        BookingService(session).reject(booking_id, scoped, on_commit=hook)
    )


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingAudienceResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="cancelBooking",
)
def cancel_booking(
    booking_id: UUID,
    data: BookingCancel,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> BookingAudienceResponse:
    # Phase 9.0.A-1 secured the customer side (owner via booking→trip→customer);
    # Phase 9.0.A-2 adds the operator side (owner via Booking.operator_id,
    # booking.decide). Either owning tenant — or an audited platform actor — may cancel.
    # The owning customer receives a customer-safe view (Phase 9.0.B); others → full.
    owner_customer = access.owner_of_booking(session, booking_id)
    owner_operator = access.operator_of_booking(session, booking_id)
    access.require_booking_cancel_access(
        principal, owner_customer_id=owner_customer, owner_operator_id=owner_operator
    )
    session.rollback()
    # A platform actor is a cross-tenant exception on the customer's booking; an owning
    # customer or owning operator records nothing (own-tenant action).
    hook = access.platform_exception_hook(
        principal,
        permission=Permission.TRIP_WRITE,
        action="cancelBooking",
        resource_type="booking",
        resource_reference=booking_id,
        owner_customer_id=owner_customer,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    booking = BookingService(session).cancel(booking_id, data, on_commit=hook)
    if access.is_customer_view(principal, owner_customer):
        return CustomerBookingResponse.model_validate(customer_booking_view(booking))
    return InternalBookingResponse.model_validate(booking)
