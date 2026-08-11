from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.bookings.domain import BookingConflictError
from sky_bridge_jet.modules.bookings.schemas import (
    BookingCancel,
    BookingConfirm,
    BookingCreate,
    BookingReject,
    BookingResponse,
)
from sky_bridge_jet.modules.bookings.services import BookingService
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse

router = APIRouter(tags=["bookings"])
DatabaseSession = Annotated[Session, Depends(get_db)]

# 404 not-found and 409 conflict use the safe envelope; the app documents 422
# and 500 globally.
_ERR = {"model": ErrorResponse}


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
    response_model=BookingResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createBooking",
)
def create_booking(data: BookingCreate, session: DatabaseSession) -> BookingResponse:
    return BookingResponse.model_validate(BookingService(session).create(data))


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    responses={404: _ERR},
    operation_id="getBooking",
)
def get_booking(booking_id: UUID, session: DatabaseSession) -> BookingResponse:
    return BookingResponse.model_validate(BookingService(session).get(booking_id))


@router.get(
    "/trip-requests/{trip_request_id}/booking",
    response_model=BookingResponse,
    responses={404: _ERR},
    operation_id="getTripRequestBooking",
)
def get_trip_booking(trip_request_id: UUID, session: DatabaseSession) -> BookingResponse:
    return BookingResponse.model_validate(BookingService(session).get_for_trip(trip_request_id))


@router.post(
    "/bookings/{booking_id}/confirm",
    response_model=BookingResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="confirmBooking",
)
def confirm_booking(
    booking_id: UUID, data: BookingConfirm, session: DatabaseSession
) -> BookingResponse:
    return BookingResponse.model_validate(BookingService(session).confirm(booking_id, data))


@router.post(
    "/bookings/{booking_id}/reject",
    response_model=BookingResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="rejectBooking",
)
def reject_booking(
    booking_id: UUID, data: BookingReject, session: DatabaseSession
) -> BookingResponse:
    return BookingResponse.model_validate(BookingService(session).reject(booking_id, data))


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="cancelBooking",
)
def cancel_booking(
    booking_id: UUID, data: BookingCancel, session: DatabaseSession
) -> BookingResponse:
    return BookingResponse.model_validate(BookingService(session).cancel(booking_id, data))
