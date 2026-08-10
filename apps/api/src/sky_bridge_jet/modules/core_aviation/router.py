from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.core_aviation.domain import (
    ConcurrencyConflictError,
    DomainValidationError,
    InvalidTripTransitionError,
    ResourceNotFoundError,
)
from sky_bridge_jet.modules.core_aviation.models import TripRequest
from sky_bridge_jet.modules.core_aviation.schemas import (
    AircraftCreate,
    AircraftResponse,
    AirportResponse,
    CustomerCreate,
    CustomerResponse,
    ErrorResponse,
    OperatorCreate,
    OperatorResponse,
    PassengerCreate,
    PassengerResponse,
    PetRequirementResponse,
    TripLegResponse,
    TripPassengerResponse,
    TripRequestCreate,
    TripRequestResponse,
    TripRequirementsResponse,
    VersionedTripCommand,
)
from sky_bridge_jet.modules.core_aviation.services import (
    AirportService,
    CustomerService,
    OperatorService,
    TripRequestService,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["core-aviation"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
    )
    correlation_id = getattr(request.state, "correlation_id", None)
    if correlation_id is not None:
        response.headers["X-Request-ID"] = correlation_id
    return response


def register_exception_handlers(app: object) -> None:
    """Install safe API error responses without adding payload values to logs."""

    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in item["loc"]],
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return _error_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="Request validation failed",
            details=details,
        )

    @app.exception_handler(ResourceNotFoundError)
    async def resource_not_found(request: Request, error: ResourceNotFoundError) -> JSONResponse:
        return _error_response(
            request,
            status_code=status.HTTP_404_NOT_FOUND,
            code=error.code,
            message=str(error),
        )

    @app.exception_handler(InvalidTripTransitionError)
    async def invalid_trip_transition(
        request: Request, error: InvalidTripTransitionError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code=error.code,
            message=str(error),
        )

    @app.exception_handler(ConcurrencyConflictError)
    async def concurrency_conflict(
        request: Request, error: ConcurrencyConflictError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code=error.code,
            message=str(error),
        )

    @app.exception_handler(DomainValidationError)
    async def domain_validation_error(
        request: Request, error: DomainValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=error.code,
            message=str(error),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, _error: IntegrityError) -> JSONResponse:
        logger.warning("persistence_constraint_conflict")
        return _error_response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code="persistence_conflict",
            message="The request conflicts with an existing resource",
        )

    @app.exception_handler(SQLAlchemyError)
    async def persistence_error(request: Request, _error: SQLAlchemyError) -> JSONResponse:
        logger.exception("persistence_failure")
        return _error_response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="persistence_failure",
            message="A persistence error prevented the request from completing",
        )


def _trip_response(trip: TripRequest) -> TripRequestResponse:
    pet = (
        PetRequirementResponse(
            pet_type=trip.pet_requirement.pet_type,
            approximate_weight_kg=trip.pet_requirement.weight_kg,
            notes=trip.pet_requirement.notes,
        )
        if trip.pet_requirement is not None
        else None
    )
    return TripRequestResponse(
        id=trip.id,
        customer_id=trip.customer_id,
        status=trip.status,
        version=trip.version,
        legs=[
            TripLegResponse.model_validate(leg)
            for leg in sorted(trip.legs, key=lambda item: item.sequence)
        ],
        passengers=[
            TripPassengerResponse(
                id=association.passenger.id,
                first_name=association.passenger.first_name,
                last_name=association.passenger.last_name,
            )
            for association in trip.passenger_associations
        ],
        requirements=TripRequirementsResponse(
            baggage_notes=trip.baggage_notes,
            catering_notes=trip.catering_notes,
            ground_transport_requested=trip.ground_transport_requested,
            special_assistance_notes=trip.special_assistance_notes,
            customer_notes=trip.customer_notes,
            pet_present=pet is not None,
            pet=pet,
        ),
        created_at=trip.created_at,
        updated_at=trip.updated_at,
    )


@router.post(
    "/customers",
    response_model=CustomerResponse,
    responses={409: {"model": ErrorResponse}},
    status_code=status.HTTP_201_CREATED,
    operation_id="createCustomer",
)
def create_customer(data: CustomerCreate, session: DatabaseSession) -> CustomerResponse:
    return CustomerResponse.model_validate(CustomerService(session).create(data))


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="getCustomer",
)
def get_customer(customer_id: UUID, session: DatabaseSession) -> CustomerResponse:
    return CustomerResponse.model_validate(CustomerService(session).get(customer_id))


@router.post(
    "/passengers",
    response_model=PassengerResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    status_code=status.HTTP_201_CREATED,
    operation_id="createPassenger",
)
def create_passenger(data: PassengerCreate, session: DatabaseSession) -> PassengerResponse:
    return PassengerResponse.model_validate(CustomerService(session).create_passenger(data))


@router.get(
    "/passengers/{passenger_id}",
    response_model=PassengerResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="getPassenger",
)
def get_passenger(passenger_id: UUID, session: DatabaseSession) -> PassengerResponse:
    return PassengerResponse.model_validate(CustomerService(session).get_passenger(passenger_id))


@router.get(
    "/airports",
    response_model=list[AirportResponse],
    operation_id="listActiveAirports",
)
def list_airports(session: DatabaseSession) -> list[AirportResponse]:
    return [
        AirportResponse.model_validate(airport) for airport in AirportService(session).list_active()
    ]


@router.get(
    "/airports/{airport_id}",
    response_model=AirportResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="getAirport",
)
def get_airport(airport_id: UUID, session: DatabaseSession) -> AirportResponse:
    return AirportResponse.model_validate(AirportService(session).get(airport_id))


@router.post(
    "/operators",
    response_model=OperatorResponse,
    responses={409: {"model": ErrorResponse}},
    status_code=status.HTTP_201_CREATED,
    operation_id="createOperator",
)
def create_operator(data: OperatorCreate, session: DatabaseSession) -> OperatorResponse:
    return OperatorResponse.model_validate(OperatorService(session).create(data))


@router.get(
    "/operators/{operator_id}",
    response_model=OperatorResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="getOperator",
)
def get_operator(operator_id: UUID, session: DatabaseSession) -> OperatorResponse:
    return OperatorResponse.model_validate(OperatorService(session).get(operator_id))


@router.post(
    "/aircraft",
    response_model=AircraftResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    status_code=status.HTTP_201_CREATED,
    operation_id="createAircraft",
)
def create_aircraft(data: AircraftCreate, session: DatabaseSession) -> AircraftResponse:
    return AircraftResponse.model_validate(OperatorService(session).create_aircraft(data))


@router.get(
    "/aircraft/{aircraft_id}",
    response_model=AircraftResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="getAircraft",
)
def get_aircraft(aircraft_id: UUID, session: DatabaseSession) -> AircraftResponse:
    return AircraftResponse.model_validate(OperatorService(session).get_aircraft(aircraft_id))


@router.post(
    "/trip-requests",
    response_model=TripRequestResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    status_code=status.HTTP_201_CREATED,
    operation_id="createDraftTripRequest",
)
def create_trip_request(data: TripRequestCreate, session: DatabaseSession) -> TripRequestResponse:
    return _trip_response(TripRequestService(session).create(data))


@router.get(
    "/trip-requests/{trip_request_id}",
    response_model=TripRequestResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="getTripRequest",
)
def get_trip_request(trip_request_id: UUID, session: DatabaseSession) -> TripRequestResponse:
    return _trip_response(TripRequestService(session).get(trip_request_id))


@router.post(
    "/trip-requests/{trip_request_id}/submit",
    response_model=TripRequestResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    operation_id="submitTripRequest",
)
def submit_trip_request(
    trip_request_id: UUID,
    command: VersionedTripCommand,
    session: DatabaseSession,
) -> TripRequestResponse:
    return _trip_response(
        TripRequestService(session).submit(
            trip_request_id, expected_version=command.expected_version
        )
    )


@router.post(
    "/trip-requests/{trip_request_id}/cancel",
    response_model=TripRequestResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    operation_id="cancelTripRequest",
)
def cancel_trip_request(
    trip_request_id: UUID,
    command: VersionedTripCommand,
    session: DatabaseSession,
) -> TripRequestResponse:
    return _trip_response(
        TripRequestService(session).cancel(
            trip_request_id, expected_version=command.expected_version
        )
    )
