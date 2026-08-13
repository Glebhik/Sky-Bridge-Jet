from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.iam.dependencies import CurrentPrincipal, require_permission
from sky_bridge_jet.modules.iam.domain import Permission
from sky_bridge_jet.modules.payments.domain import PaymentConflictError
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.provider import (
    PaymentProviderError,
    ProviderErrorCategory,
)
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
# Refunds are a high-consequence financial action bound to a platform finance/admin
# principal (Phase 8): an arbitrary authenticated user cannot refund a payment.
_REQUIRE_PAYMENT_REFUND = require_permission(Permission.PAYMENT_REFUND)

# Provider infrastructure failures map to safe, provider-neutral HTTP responses.
# No provider key, raw response body, or stack trace ever reaches the client.
_PROVIDER_ERROR_HTTP: dict[ProviderErrorCategory, tuple[int, str]] = {
    ProviderErrorCategory.PROVIDER_UNAVAILABLE: (
        status.HTTP_502_BAD_GATEWAY,
        "payment_provider_unavailable",
    ),
    ProviderErrorCategory.PROVIDER_DECLINED: (
        status.HTTP_402_PAYMENT_REQUIRED,
        "payment_declined",
    ),
    ProviderErrorCategory.PROVIDER_REQUIRES_ACTION: (
        status.HTTP_409_CONFLICT,
        "payment_requires_action",
    ),
    ProviderErrorCategory.PROVIDER_INVALID_STATE: (
        status.HTTP_409_CONFLICT,
        "payment_provider_invalid_state",
    ),
    ProviderErrorCategory.PROVIDER_CONFIGURATION_ERROR: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "payment_provider_misconfigured",
    ),
    ProviderErrorCategory.PROVIDER_AUTHENTICATION_ERROR: (
        status.HTTP_502_BAD_GATEWAY,
        "payment_provider_authentication_error",
    ),
}

_PROVIDER_ERROR_MESSAGE = "The payment provider could not complete the request"


def _safe_envelope(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": None}},
    )
    correlation_id = getattr(request.state, "correlation_id", None)
    if correlation_id is not None:
        response.headers["X-Request-ID"] = correlation_id
    return response


def register_payment_exception_handlers(app: object) -> None:
    """Register the payment conflict/provider handlers using the safe error envelope."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(PaymentConflictError)
    async def payment_conflict(request: Request, error: PaymentConflictError) -> JSONResponse:
        return _safe_envelope(
            request, status_code=status.HTTP_409_CONFLICT, code=error.code, message=str(error)
        )

    @app.exception_handler(PaymentProviderError)
    async def payment_provider_error(request: Request, error: PaymentProviderError) -> JSONResponse:
        status_code, code = _PROVIDER_ERROR_HTTP.get(
            error.category,
            (status.HTTP_502_BAD_GATEWAY, "payment_provider_error"),
        )
        # The provider message is intentionally discarded; a fixed safe message is
        # returned so no provider-supplied text (which could echo a key) leaks.
        return _safe_envelope(
            request, status_code=status_code, code=code, message=_PROVIDER_ERROR_MESSAGE
        )


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
    responses={403: _ERR, 404: _ERR},
    operation_id="getBookingPayment",
)
def get_booking_payment(
    booking_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentResponse:
    # PaymentResponse exposes platform_fee_minor / operator_amount_minor; the
    # customer-safe payment-status projection is Phase 9.0.B. Platform viewers get the
    # full response; ownership (payment→booking→trip→customer) is enforced.
    owner = access.owner_of_booking(session, booking_id)
    access.require_confidential_read(principal, Permission.PAYMENT_READ, owner)
    access.audit_platform_read(
        session,
        principal,
        permission=Permission.PAYMENT_READ,
        action="getBookingPayment",
        resource_type="booking",
        resource_reference=booking_id,
        owner_customer_id=owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
    return _payment(PaymentService(session).get_for_booking(booking_id))


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getPayment",
)
def get_payment(
    payment_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentResponse:
    owner = access.owner_of_payment(session, payment_id)
    access.require_confidential_read(principal, Permission.PAYMENT_READ, owner)
    access.audit_platform_read(
        session,
        principal,
        permission=Permission.PAYMENT_READ,
        action="getPayment",
        resource_type="payment",
        resource_reference=payment_id,
        owner_customer_id=owner,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
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
    dependencies=[_REQUIRE_PAYMENT_REFUND],
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
