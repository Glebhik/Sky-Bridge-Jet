from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sky_bridge_jet.core.config import get_settings
from sky_bridge_jet.core.stripe_gateway import (
    StripeGateway,
    WebhookSignatureError,
    build_stripe_gateway,
)
from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.modules.core_aviation.schemas import ErrorResponse
from sky_bridge_jet.modules.financials.domain import FinancialConflictError
from sky_bridge_jet.modules.financials.reconciliation import (
    NormalizedProviderEvent,
    WebhookReconciliationService,
)
from sky_bridge_jet.modules.financials.schemas import (
    ConnectedAccountResponse,
    FinancialEligibilityResponse,
    OnboardingLinkResponse,
    WebhookAckResponse,
)
from sky_bridge_jet.modules.financials.services import FinancialOnboardingService
from sky_bridge_jet.modules.payments.domain import PaymentProviderKind

router = APIRouter(tags=["financials"])
DatabaseSession = Annotated[Session, Depends(get_db)]
_ERR = {"model": ErrorResponse}


class WebhookNotConfiguredError(Exception):
    """Raised when the Stripe webhook endpoint is hit but Stripe is not configured."""


@dataclass
class StripeWebhookContext:
    gateway: StripeGateway
    webhook_secret: str


def get_stripe_webhook_context() -> StripeWebhookContext:
    """Build the webhook verification context; tests override this dependency."""
    settings = get_settings()
    if not settings.stripe_enabled or not settings.stripe_webhook_secret:
        raise WebhookNotConfiguredError
    return StripeWebhookContext(
        gateway=build_stripe_gateway(settings.stripe_secret_key),
        webhook_secret=settings.stripe_webhook_secret,
    )


def _safe_error(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": None}},
    )
    correlation_id = getattr(request.state, "correlation_id", None)
    if correlation_id is not None:
        response.headers["X-Request-ID"] = correlation_id
    return response


def register_financial_exception_handlers(app: object) -> None:
    """Register financial conflict and webhook error handlers (safe envelopes)."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("Expected a FastAPI application")

    @app.exception_handler(FinancialConflictError)
    async def financial_conflict(request: Request, error: FinancialConflictError) -> JSONResponse:
        return _safe_error(
            request, status_code=status.HTTP_409_CONFLICT, code=error.code, message=str(error)
        )

    @app.exception_handler(WebhookSignatureError)
    async def webhook_signature(request: Request, _error: WebhookSignatureError) -> JSONResponse:
        return _safe_error(
            request,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_webhook_signature",
            message="The webhook signature could not be verified",
        )

    @app.exception_handler(WebhookNotConfiguredError)
    async def webhook_not_configured(
        request: Request, _error: WebhookNotConfiguredError
    ) -> JSONResponse:
        return _safe_error(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="webhook_not_configured",
            message="Provider webhook processing is not enabled",
        )


@router.post(
    "/operators/{operator_id}/financial-account",
    response_model=ConnectedAccountResponse,
    responses={404: _ERR, 409: _ERR},
    status_code=status.HTTP_201_CREATED,
    operation_id="createOperatorConnectedAccount",
)
def create_account(operator_id: UUID, session: DatabaseSession) -> ConnectedAccountResponse:
    return ConnectedAccountResponse.model_validate(
        FinancialOnboardingService(session).create_account(operator_id)
    )


@router.get(
    "/operators/{operator_id}/financial-account",
    response_model=ConnectedAccountResponse,
    responses={404: _ERR},
    operation_id="getOperatorConnectedAccount",
)
def get_account(operator_id: UUID, session: DatabaseSession) -> ConnectedAccountResponse:
    return ConnectedAccountResponse.model_validate(
        FinancialOnboardingService(session).get_account(operator_id)
    )


@router.post(
    "/operators/{operator_id}/financial-account/onboarding-link",
    response_model=OnboardingLinkResponse,
    responses={404: _ERR},
    operation_id="createOperatorOnboardingLink",
)
def create_onboarding_link(operator_id: UUID, session: DatabaseSession) -> OnboardingLinkResponse:
    link = FinancialOnboardingService(session).create_onboarding_link(operator_id)
    return OnboardingLinkResponse(url=link.url, expires_at=link.expires_at)


@router.post(
    "/operators/{operator_id}/financial-account/synchronize",
    response_model=ConnectedAccountResponse,
    responses={404: _ERR},
    operation_id="synchronizeOperatorConnectedAccount",
)
def synchronize_account(operator_id: UUID, session: DatabaseSession) -> ConnectedAccountResponse:
    return ConnectedAccountResponse.model_validate(
        FinancialOnboardingService(session).synchronize(operator_id)
    )


@router.get(
    "/operators/{operator_id}/financial-eligibility",
    response_model=FinancialEligibilityResponse,
    responses={404: _ERR},
    operation_id="getOperatorFinancialEligibility",
)
def financial_eligibility(
    operator_id: UUID, session: DatabaseSession
) -> FinancialEligibilityResponse:
    decision = FinancialOnboardingService(session).eligibility(operator_id)
    return FinancialEligibilityResponse(
        operator_id=operator_id, eligible=decision.eligible, reasons=decision.reasons
    )


@router.post(
    "/webhooks/stripe",
    response_model=WebhookAckResponse,
    responses={400: _ERR, 503: _ERR},
    operation_id="stripeWebhook",
)
async def stripe_webhook(
    request: Request,
    session: DatabaseSession,
    context: Annotated[StripeWebhookContext, Depends(get_stripe_webhook_context)],
) -> WebhookAckResponse:
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature")
    event_view = context.gateway.construct_webhook_event(
        payload=payload, signature_header=signature, webhook_secret=context.webhook_secret
    )
    normalized = NormalizedProviderEvent(
        provider=PaymentProviderKind.STRIPE,
        event_id=event_view.id,
        event_type=event_view.type,
        object_id=event_view.object_id,
        data=event_view.data,
    )
    result = WebhookReconciliationService(session).process(normalized)
    return WebhookAckResponse(received=True, status=result.status, duplicate=result.duplicate)
