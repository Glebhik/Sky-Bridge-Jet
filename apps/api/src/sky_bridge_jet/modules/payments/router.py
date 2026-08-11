from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.payments.domain import PaymentConflictError
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.schemas import (
    AllocationResponse,
    PaymentAuthorize,
    PaymentCapture,
    PaymentResponse,
    PaymentVoid,
    RefundCreate,
    RefundResponse,
)
from sky_bridge_jet.modules.payments.services import PaymentService

router = APIRouter(tags=["payments"])
DatabaseSession = Annotated[Session, Depends(get_db)]

_ERR = {"model": ErrorResponse}


def register_payment_exception_handlers(app: object) -> None:
    """Register the payment conflict handler using the shared safe error envelope."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(PaymentConflictError)
    async def payment_conflict(request: Request, error: PaymentConflictError) -> JSONResponse:
        response = JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": {"code": error.code, "message": str(error), "details": None}},
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id is not None:
            response.headers["X-Request-ID"] = correlation_id
        return response


def _payment(payment: Payment) -> PaymentResponse:
    return PaymentResponse.model_validate(payment)


def _refund(operation: PaymentOperation, currency: str) -> RefundResponse:
    return RefundResponse(
        id=operation.id,
        payment_id=operation.payment_id,
        amount_minor=operation.amount_minor,
        currency=currency,
        result=operation.result,
        provider_reference=operation.provider_reference,
        failure_code=operation.failure_code,
        created_at=operation.created_at,
    )


@router.post(
    "/bookings/{booking_id}/payment",
    response_model=PaymentResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createBookingPayment",
)
def create_payment(booking_id: UUID, session: DatabaseSession) -> PaymentResponse:
    return _payment(PaymentService(session).create_for_booking(booking_id))


@router.get(
    "/bookings/{booking_id}/payment",
    response_model=PaymentResponse,
    responses={404: _ERR},
    operation_id="getBookingPayment",
)
def get_booking_payment(booking_id: UUID, session: DatabaseSession) -> PaymentResponse:
    return _payment(PaymentService(session).get_for_booking(booking_id))


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentResponse,
    responses={404: _ERR},
    operation_id="getPayment",
)
def get_payment(payment_id: UUID, session: DatabaseSession) -> PaymentResponse:
    return _payment(PaymentService(session).get(payment_id))


@router.post(
    "/payments/{payment_id}/authorize",
    response_model=PaymentResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="authorizePayment",
)
def authorize_payment(
    payment_id: UUID, data: PaymentAuthorize, session: DatabaseSession
) -> PaymentResponse:
    return _payment(PaymentService(session).authorize(payment_id, data))


@router.post(
    "/payments/{payment_id}/capture",
    response_model=PaymentResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="capturePayment",
)
def capture_payment(
    payment_id: UUID, data: PaymentCapture, session: DatabaseSession
) -> PaymentResponse:
    return _payment(PaymentService(session).capture(payment_id, data))


@router.post(
    "/payments/{payment_id}/void",
    response_model=PaymentResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="voidPayment",
)
def void_payment(payment_id: UUID, data: PaymentVoid, session: DatabaseSession) -> PaymentResponse:
    return _payment(PaymentService(session).void(payment_id, data))


@router.post(
    "/payments/{payment_id}/refunds",
    response_model=RefundResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createPaymentRefund",
)
def create_refund(payment_id: UUID, data: RefundCreate, session: DatabaseSession) -> RefundResponse:
    operation = PaymentService(session).refund(payment_id, data)
    return _refund(operation, operation.payment.currency)


@router.get(
    "/payments/{payment_id}/refunds",
    response_model=list[RefundResponse],
    responses={404: _ERR},
    operation_id="listPaymentRefunds",
)
def list_refunds(payment_id: UUID, session: DatabaseSession) -> list[RefundResponse]:
    service = PaymentService(session)
    payment = service.get(payment_id)
    return [_refund(operation, payment.currency) for operation in service.list_refunds(payment_id)]


@router.get(
    "/payments/{payment_id}/allocation",
    response_model=AllocationResponse,
    responses={404: _ERR},
    operation_id="getPaymentAllocation",
)
def get_allocation(payment_id: UUID, session: DatabaseSession) -> AllocationResponse:
    payment, eligibility = PaymentService(session).get_allocation(payment_id)
    return AllocationResponse(
        payment_id=payment.id,
        booking_id=payment.booking_id,
        currency=payment.currency,
        operator_amount_minor=payment.operator_amount_minor,
        platform_fee_minor=payment.platform_fee_minor,
        tax_amount_minor=payment.tax_amount_minor,
        total_customer_amount_minor=payment.total_amount_minor,
        captured_amount_minor=payment.captured_amount_minor,
        refunded_amount_minor=payment.refunded_amount_minor,
        settlement_eligibility=eligibility,
    )
