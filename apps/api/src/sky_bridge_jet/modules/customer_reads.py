"""Customer-scoped "my" list endpoints (Phase 9.0.B, ADR-045).

Three read-only list endpoints for the authenticated customer's own resources. The
active CUSTOMER organization is resolved and validated server-side; the canonical
``customer_id`` comes from that organization — never from the client. Every query is
**filtered by tenant in SQL before materialization** (never load-all-then-filter),
uses deterministic ordering, and is bounded by pagination. Responses use the
customer-safe projections, so no internal/operator/platform field is ever returned.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.bookings.models import Booking
from sky_bridge_jet.modules.core_aviation.models import TripRequest
from sky_bridge_jet.modules.core_aviation.router import _trip_response
from sky_bridge_jet.modules.core_aviation.schemas import TripRequestResponse
from sky_bridge_jet.modules.customer_views import (
    CustomerBookingView,
    CustomerPaymentStatusView,
    customer_booking_view,
    customer_payment_view,
)
from sky_bridge_jet.modules.iam.dependencies import ActiveOrganization, CurrentPrincipal
from sky_bridge_jet.modules.payments.models import Payment

router = APIRouter(tags=["customer-portal"])
DatabaseSession = Annotated[Session, Depends(get_db)]

# Bounded pagination: a safe default page size and a hard maximum. Deterministic
# ordering (created_at desc, then id) keeps pages stable across requests.
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
_DEFAULT_LIMIT = 20
CanonicalBookingId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]


class CustomerReadService:
    """Tenant-filtered list queries over the customer's own resource chain."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_trip_requests(
        self, customer_id: UUID, *, limit: int, offset: int
    ) -> list[TripRequest]:
        return list(
            self.session.scalars(
                select(TripRequest)
                .where(TripRequest.customer_id == customer_id)
                .order_by(TripRequest.created_at.desc(), TripRequest.id)
                .limit(limit)
                .offset(offset)
            ).all()
        )

    def list_bookings(self, customer_id: UUID, *, limit: int, offset: int) -> list[Booking]:
        return list(
            self.session.scalars(
                select(Booking)
                .join(TripRequest, Booking.trip_request_id == TripRequest.id)
                .where(TripRequest.customer_id == customer_id)
                .order_by(Booking.created_at.desc(), Booking.id)
                .limit(limit)
                .offset(offset)
            ).all()
        )

    def list_payments(
        self,
        customer_id: UUID,
        *,
        limit: int,
        offset: int,
        booking_ids: tuple[UUID, ...] | None = None,
    ) -> list[Payment]:
        statement = (
            select(Payment)
            .join(Booking, Payment.booking_id == Booking.id)
            .join(TripRequest, Booking.trip_request_id == TripRequest.id)
            .where(TripRequest.customer_id == customer_id)
            .order_by(Payment.created_at.desc(), Payment.id)
        )
        if booking_ids is not None:
            statement = statement.where(Payment.booking_id.in_(booking_ids))
        else:
            statement = statement.limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())


def _booking_id_filter(raw_values: list[CanonicalBookingId] | None) -> tuple[UUID, ...] | None:
    if raw_values is None:
        return None
    parsed: list[UUID] = []
    for raw in raw_values:
        parsed.append(UUID(raw))
    return tuple(dict.fromkeys(parsed))


@router.get(
    "/me/trip-requests",
    response_model=list[TripRequestResponse],
    operation_id="listMyTripRequests",
)
def list_my_trip_requests(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = _DEFAULT_LIMIT,
    offset: Offset = 0,
) -> list[TripRequestResponse]:
    customer_id = access.active_customer_id(principal, active_organization)
    trips = CustomerReadService(session).list_trip_requests(customer_id, limit=limit, offset=offset)
    return [_trip_response(trip) for trip in trips]


@router.get(
    "/me/bookings",
    response_model=list[CustomerBookingView],
    operation_id="listMyBookings",
)
def list_my_bookings(
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    limit: Limit = _DEFAULT_LIMIT,
    offset: Offset = 0,
) -> list[CustomerBookingView]:
    customer_id = access.active_customer_id(principal, active_organization)
    bookings = CustomerReadService(session).list_bookings(customer_id, limit=limit, offset=offset)
    return [customer_booking_view(booking) for booking in bookings]


@router.get(
    "/me/payments",
    response_model=list[CustomerPaymentStatusView],
    operation_id="listMyPayments",
)
def list_my_payments(
    request: Request,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
    booking_id: Annotated[list[CanonicalBookingId] | None, Query(max_length=100)] = None,
    limit: Limit = _DEFAULT_LIMIT,
    offset: Offset = 0,
) -> list[CustomerPaymentStatusView]:
    customer_id = access.active_customer_id(principal, active_organization)
    booking_ids = _booking_id_filter(booking_id)
    if booking_ids is not None and (
        "limit" in request.query_params or "offset" in request.query_params
    ):
        raise HTTPException(status_code=422, detail="Filtered lookup does not accept pagination")
    payments = CustomerReadService(session).list_payments(
        customer_id, limit=limit, offset=offset, booking_ids=booking_ids
    )
    return [customer_payment_view(payment) for payment in payments]
