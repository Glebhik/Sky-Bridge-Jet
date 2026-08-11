from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
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


@router.post(
    "/offers",
    response_model=OperatorOfferResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createOperatorOffer",
)
def create_offer(data: OperatorOfferCreate, session: DatabaseSession) -> OperatorOfferResponse:
    return _to_response(OperatorOfferService(session).create(data))


@router.get(
    "/offers/{offer_id}",
    response_model=OperatorOfferResponse,
    responses={404: _ERR},
    operation_id="getOperatorOffer",
)
def get_offer(offer_id: UUID, session: DatabaseSession) -> OperatorOfferResponse:
    return _to_response(OperatorOfferService(session).get(offer_id))


@router.patch(
    "/offers/{offer_id}",
    response_model=OperatorOfferResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="updateDraftOperatorOffer",
)
def update_offer(
    offer_id: UUID, data: OperatorOfferUpdate, session: DatabaseSession
) -> OperatorOfferResponse:
    return _to_response(OperatorOfferService(session).update_draft(offer_id, data))


@router.post(
    "/offers/{offer_id}/submit",
    response_model=OperatorOfferResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="submitOperatorOffer",
)
def submit_offer(offer_id: UUID, session: DatabaseSession) -> OperatorOfferResponse:
    return _to_response(OperatorOfferService(session).submit(offer_id))


@router.post(
    "/offers/{offer_id}/withdraw",
    response_model=OperatorOfferResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="withdrawOperatorOffer",
)
def withdraw_offer(offer_id: UUID, session: DatabaseSession) -> OperatorOfferResponse:
    return _to_response(OperatorOfferService(session).withdraw(offer_id))


@router.get(
    "/trip-requests/{trip_request_id}/offers",
    response_model=list[OperatorOfferResponse],
    responses={404: _ERR},
    operation_id="listTripRequestOffers",
)
def list_trip_offers(
    trip_request_id: UUID, session: DatabaseSession
) -> list[OperatorOfferResponse]:
    offers = OperatorOfferService(session).list_for_trip(trip_request_id)
    return [_to_response(offer) for offer in offers]


@router.post(
    "/trip-requests/{trip_request_id}/offers/{offer_id}/select",
    response_model=OperatorOfferResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="selectOperatorOffer",
)
def select_offer(
    trip_request_id: UUID, offer_id: UUID, session: DatabaseSession
) -> OperatorOfferResponse:
    return _to_response(OperatorOfferService(session).select(trip_request_id, offer_id))
