from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules import access
from sky_bridge_jet.modules.audience import (
    CustomerPaymentResponse,
    InternalPaymentResponse,
    PaymentAudienceResponse,
)
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.customer_views import customer_payment_view
from sky_bridge_jet.modules.iam.dependencies import (
    ActiveOrganization,
    CurrentPrincipal,
    require_permission,
)
from sky_bridge_jet.modules.iam.domain import AuthorizationError, Permission
from sky_bridge_jet.modules.payments.domain import (
    PaymentConflictError,
    PaymentOperationResult,
    PaymentOperationType,
)
from sky_bridge_jet.modules.payments.models import Payment, PaymentOperation
from sky_bridge_jet.modules.payments.provider import (
    PaymentProviderError,
    ProviderErrorCategory,
)
from sky_bridge_jet.modules.payments.schemas import (
    AllocationResponse,
    CustomerPaymentInitiate,
    CustomerPaymentInitiateResponse,
    PaymentAuthorize,
    PaymentCapture,
    PaymentResponse,
    PaymentVoid,
    PlatformPaymentDetailResponse,
    PlatformPaymentExceptionResponse,
    PlatformPaymentOperationResponse,
    RefundCreate,
    RefundResponse,
)
from sky_bridge_jet.modules.payments.services import PaymentService
from sky_bridge_jet.modules.pilot_governance.services import PilotAccessService

router = APIRouter(tags=["payments"])
DatabaseSession = Annotated[Session, Depends(get_db)]

_ERR = {"model": ErrorResponse}
# Refunds are a high-consequence financial action bound to the payment.refund
# permission (Phase 8): an arbitrary authenticated user cannot refund a payment.
_REQUIRE_PAYMENT_REFUND = require_permission(Permission.PAYMENT_REFUND)
# Internal payment operations (create/authorize/capture/void) are platform-only
# (Phase 9.0.A-3): payment.operate is held solely by PLATFORM_ADMIN and PRODUCT_OWNER.


def _require_platform_payment_permission(permission: Permission) -> Any:
    def _dependency(principal: CurrentPrincipal) -> None:
        if not access.has_platform_permission(principal, permission):
            raise AuthorizationError("Platform payment access is required")

    return Depends(_dependency)


_REQUIRE_PAYMENT_OPERATE = _require_platform_payment_permission(Permission.PAYMENT_OPERATE)
_REQUIRE_PAYMENT_READ = _require_platform_payment_permission(Permission.PAYMENT_READ)


def _correlation(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


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


def _platform_operation(operation: PaymentOperation) -> PlatformPaymentOperationResponse:
    return PlatformPaymentOperationResponse.model_validate(operation)


@router.get(
    "/platform/payments/exceptions",
    response_model=list[PlatformPaymentExceptionResponse],
    operation_id="listPlatformPaymentExceptions",
    dependencies=[_REQUIRE_PAYMENT_READ],
)
def list_platform_payment_exceptions(
    session: DatabaseSession,
    result: Annotated[list[PaymentOperationResult] | None, Query()] = None,
    operation: PaymentOperationType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlatformPaymentExceptionResponse]:
    selected_results = result or [
        PaymentOperationResult.PENDING,
        PaymentOperationResult.UNKNOWN,
        PaymentOperationResult.FAILED,
    ]
    rows = PaymentService(session).list_platform_exceptions(
        results=selected_results, operation=operation, limit=limit, offset=offset
    )
    return [
        PlatformPaymentExceptionResponse(
            **_platform_operation(item).model_dump(),
            booking_id=payment.booking_id,
            payment_reference=payment.reference,
            payment_status=payment.status,
            currency=payment.currency,
            total_amount_minor=payment.total_amount_minor,
            authorized_amount_minor=payment.authorized_amount_minor,
            captured_amount_minor=payment.captured_amount_minor,
            refunded_amount_minor=payment.refunded_amount_minor,
            can_reconcile=item.result is PaymentOperationResult.UNKNOWN
            and item.operation is not PaymentOperationType.REFUND,
        )
        for item, payment in rows
    ]


@router.get(
    "/platform/payments/{payment_id}",
    response_model=PlatformPaymentDetailResponse,
    responses={404: _ERR},
    operation_id="getPlatformPaymentDetail",
    dependencies=[_REQUIRE_PAYMENT_READ],
)
def get_platform_payment_detail(
    payment_id: UUID,
    session: DatabaseSession,
    operation_limit: Annotated[int, Query(ge=1, le=100)] = 100,
    operation_offset: Annotated[int, Query(ge=0)] = 0,
) -> PlatformPaymentDetailResponse:
    payment, operations = PaymentService(session).get_platform_detail(
        payment_id, limit=operation_limit, offset=operation_offset
    )
    return PlatformPaymentDetailResponse(
        **PaymentResponse.model_validate(payment).model_dump(exclude={"client_action"}),
        operations=[_platform_operation(item) for item in operations],
    )


@router.post(
    "/platform/payment-operations/{operation_id}/reconcile",
    response_model=PlatformPaymentDetailResponse,
    responses={404: _ERR, 409: _ERR},
    operation_id="reconcilePlatformPaymentOperation",
    dependencies=[_REQUIRE_PAYMENT_OPERATE],
)
def reconcile_platform_payment_operation(
    operation_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PlatformPaymentDetailResponse:
    hook = access.payment_operation_hook(
        principal,
        permission=Permission.PAYMENT_OPERATE,
        action="reconcilePlatformPaymentOperation",
        resource_type="payment_operation",
        resource_reference=operation_id,
        correlation_id=_correlation(request),
    )
    service = PaymentService(session)
    payment = service.reconcile_operation(operation_id, on_commit=hook)
    payment, operations = service.get_platform_detail(payment.id, limit=100, offset=0)
    return PlatformPaymentDetailResponse(
        **PaymentResponse.model_validate(payment).model_dump(exclude={"client_action"}),
        operations=[_platform_operation(item) for item in operations],
    )


@router.post(
    "/bookings/{booking_id}/payment",
    response_model=PaymentResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createBookingPayment",
    dependencies=[_REQUIRE_PAYMENT_OPERATE],
)
def create_payment(
    booking_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentResponse:
    # Internal/trusted platform action (B3/D): gated to payment.operate above; the
    # Booking is resolved server-side and no ownership id is trusted from the body.
    hook = access.payment_operation_hook(
        principal,
        permission=Permission.PAYMENT_OPERATE,
        action="createBookingPayment",
        resource_type="booking",
        resource_reference=booking_id,
        correlation_id=_correlation(request),
    )
    return _payment(PaymentService(session).create_for_booking(booking_id, on_commit=hook))


@router.post(
    "/bookings/{booking_id}/payment/initiate",
    response_model=CustomerPaymentInitiateResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    operation_id="initiateBookingPayment",
)
def initiate_booking_payment(
    booking_id: UUID,
    data: CustomerPaymentInitiate,
    request: Request,
    principal: CurrentPrincipal,
    active_organization: ActiveOrganization,
    session: DatabaseSession,
) -> CustomerPaymentInitiateResponse:
    """Initiate fake/provider-neutral authorization for the customer's own booking."""
    active_customer = access.active_customer_id(principal, active_organization)
    owner = access.owner_of_booking(session, booking_id)
    access.require_customer_access(principal, Permission.PAYMENT_INITIATE, owner)
    if owner != active_customer:
        # Preserve cross-tenant concealment even when the principal has several
        # legitimate customer memberships and selected the wrong active one.
        from sky_bridge_jet.modules.core_aviation.domain import ResourceNotFoundError

        raise ResourceNotFoundError("Booking was not found")
    PilotAccessService(session).require_payment_initiation(owner)
    session.rollback()
    payment = PaymentService(session).initiate_for_customer(booking_id, data)
    # The initiation response alone may carry the transient Stripe client action.
    # The customer read projection remains action/secret-free.
    return CustomerPaymentInitiateResponse.model_validate(payment)


@router.get(
    "/bookings/{booking_id}/payment",
    response_model=PaymentAudienceResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getBookingPayment",
)
def get_booking_payment(
    booking_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentAudienceResponse:
    # Phase 9.0.B: the owning customer receives a customer-safe payment *status* view; a
    # platform viewer gets the full response (and is audited); cross-tenant → 404.
    owner = access.owner_of_booking(session, booking_id)
    access.require_customer_access(principal, Permission.PAYMENT_READ, owner)
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
    payment = PaymentService(session).get_for_booking(booking_id)
    if access.is_customer_view(principal, owner):
        return CustomerPaymentResponse.model_validate(customer_payment_view(payment))
    return InternalPaymentResponse.model_validate(payment)


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentAudienceResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getPayment",
)
def get_payment(
    payment_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentAudienceResponse:
    owner = access.owner_of_payment(session, payment_id)
    access.require_customer_access(principal, Permission.PAYMENT_READ, owner)
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
    payment = PaymentService(session).get(payment_id)
    if access.is_customer_view(principal, owner):
        return CustomerPaymentResponse.model_validate(customer_payment_view(payment))
    return InternalPaymentResponse.model_validate(payment)


def _operation_hook(
    request: Request, principal: CurrentPrincipal, action: str, payment_id: UUID
) -> access.AuditHook:
    return access.payment_operation_hook(
        principal,
        permission=Permission.PAYMENT_OPERATE,
        action=action,
        resource_type="payment",
        resource_reference=payment_id,
        correlation_id=_correlation(request),
    )


@router.post(
    "/payments/{payment_id}/authorize",
    response_model=PaymentResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="authorizePayment",
    dependencies=[_REQUIRE_PAYMENT_OPERATE],
)
def authorize_payment(
    payment_id: UUID,
    data: PaymentAuthorize,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentResponse:
    hook = _operation_hook(request, principal, "authorizePayment", payment_id)
    return _payment(PaymentService(session).authorize(payment_id, data, on_commit=hook))


@router.post(
    "/payments/{payment_id}/capture",
    response_model=PaymentResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="capturePayment",
    dependencies=[_REQUIRE_PAYMENT_OPERATE],
)
def capture_payment(
    payment_id: UUID,
    data: PaymentCapture,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentResponse:
    hook = _operation_hook(request, principal, "capturePayment", payment_id)
    return _payment(PaymentService(session).capture(payment_id, data, on_commit=hook))


@router.post(
    "/payments/{payment_id}/void",
    response_model=PaymentResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    operation_id="voidPayment",
    dependencies=[_REQUIRE_PAYMENT_OPERATE],
)
def void_payment(
    payment_id: UUID,
    data: PaymentVoid,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> PaymentResponse:
    hook = _operation_hook(request, principal, "voidPayment", payment_id)
    return _payment(PaymentService(session).void(payment_id, data, on_commit=hook))


@router.post(
    "/payments/{payment_id}/refunds",
    response_model=RefundResponse,
    responses={403: _ERR, 404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createPaymentRefund",
    dependencies=[_REQUIRE_PAYMENT_REFUND],
)
def create_refund(
    payment_id: UUID,
    data: RefundCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> RefundResponse:
    # Refunds remain gated to payment.refund (unchanged, Phase 8); a successful refund
    # is append-only audited atomically with the mutation. The permission recorded is
    # payment.refund — the refund capability is NOT folded into payment.operate.
    hook = access.payment_operation_hook(
        principal,
        permission=Permission.PAYMENT_REFUND,
        action="createPaymentRefund",
        resource_type="payment",
        resource_reference=payment_id,
        correlation_id=_correlation(request),
    )
    operation = PaymentService(session).refund(payment_id, data, on_commit=hook)
    return _refund(operation, operation.payment.currency)


def _require_financial_read(
    session: Session,
    request: Request,
    principal: CurrentPrincipal,
    *,
    action: str,
    payment_id: UUID,
) -> None:
    # Allocation and refund-list responses expose the internal operator/platform split,
    # settlement eligibility, and provider references. Only a platform payment.read
    # viewer receives them; an owning customer/operator is temporarily denied (403), a
    # cross-tenant probe is concealed (404). Platform reads are append-only audited.
    owner_customer = access.owner_of_payment(session, payment_id)
    owner_operator = access.operator_of_payment(session, payment_id)
    access.require_financial_platform_read(
        principal,
        Permission.PAYMENT_READ,
        owner_customer_id=owner_customer,
        owner_operator_id=owner_operator,
    )
    access.audit_platform_read(
        session,
        principal,
        permission=Permission.PAYMENT_READ,
        action=action,
        resource_type="payment",
        resource_reference=payment_id,
        owner_customer_id=owner_customer,
        correlation_id=_correlation(request),
    )


@router.get(
    "/payments/{payment_id}/refunds",
    response_model=list[RefundResponse],
    responses={403: _ERR, 404: _ERR},
    operation_id="listPaymentRefunds",
)
def list_refunds(
    payment_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> list[RefundResponse]:
    _require_financial_read(
        session, request, principal, action="listPaymentRefunds", payment_id=payment_id
    )
    service = PaymentService(session)
    payment = service.get(payment_id)
    return [_refund(operation, payment.currency) for operation in service.list_refunds(payment_id)]


@router.get(
    "/payments/{payment_id}/allocation",
    response_model=AllocationResponse,
    responses={403: _ERR, 404: _ERR},
    operation_id="getPaymentAllocation",
)
def get_allocation(
    payment_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> AllocationResponse:
    _require_financial_read(
        session, request, principal, action="getPaymentAllocation", payment_id=payment_id
    )
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
