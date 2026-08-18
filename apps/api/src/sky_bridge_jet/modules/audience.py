"""Typed audience-aware response contracts for the shared resource routes (ADR-046).

Eight routes are reachable by more than one audience and must return a *different*
schema depending on who is asking: the owning customer receives a customer-safe
projection, while an owning operator or an authorized platform actor receives the full
internal model. Phase 9.0.B implemented that split at runtime with ``response_model=None``,
which left the OpenAPI 2xx body untyped and disabled FastAPI response validation.

This module restores a *validated, accurately documented* contract without weakening the
confidentiality boundary. For each shared route we expose a **discriminated union** of two
distinct structural models tagged by a required ``response_audience`` literal
(``"customer"`` / ``"internal"``):

- the ``Customer*`` variants subclass the Phase 9.0.B customer-safe views, so they
  *structurally* cannot carry the operator/platform split, allocation/settlement data,
  provider references, raw operations, idempotency keys, or audit metadata — even nested;
- the ``Internal*`` variants subclass the unchanged internal response schemas.

The variants are **shared-route-specific wrappers**: subclassing leaves the base schemas
(``CustomerBookingView``/``CustomerPaymentStatusView`` used by the ``/me`` lists, and
``BookingResponse``/``OperatorOfferResponse``/``PaymentResponse`` used by the
operator/platform routes) untouched, so no unrelated endpoint's contract changes. The only
additive change is the always-present ``response_audience`` discriminator on these eight
responses.

Because the union is discriminated, Pydantic selects the variant by the literal value of a
concrete instance the handler builds — there is no positional coercion and no silent field
stripping. The handler decides the audience server-side (``access.is_customer_view``) and
constructs the matching envelope; a plain internal object without the discriminator cannot
validate as the customer variant, so a mis-wired handler fails closed rather than leaking.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from sky_bridge_jet.modules.bookings.schemas import BookingResponse
from sky_bridge_jet.modules.customer_views import (
    CustomerBookingView,
    CustomerOfferView,
    CustomerPaymentStatusView,
)
from sky_bridge_jet.modules.offers.schemas import OperatorOfferResponse
from sky_bridge_jet.modules.payments.schemas import PaymentResponse

# The discriminator field name and its two literal values (ADR-046). Kept as constants so
# tests and handlers reference one source of truth. The audience values are typed as their
# ``Literal`` so they can serve as the discriminated variants' field defaults.
AUDIENCE_DISCRIMINATOR = "response_audience"
CUSTOMER_AUDIENCE: Literal["customer"] = "customer"
INTERNAL_AUDIENCE: Literal["internal"] = "internal"


# --------------------------------------------------------------------------- #
# Offer
# --------------------------------------------------------------------------- #
class CustomerOfferResponse(CustomerOfferView):
    """Customer-safe offer contract for the shared routes (discriminated variant)."""

    response_audience: Literal["customer"] = CUSTOMER_AUDIENCE


class InternalOfferResponse(OperatorOfferResponse):
    """Full internal offer contract for the shared routes (discriminated variant)."""

    response_audience: Literal["internal"] = INTERNAL_AUDIENCE


OfferAudienceResponse = Annotated[
    CustomerOfferResponse | InternalOfferResponse,
    Field(discriminator=AUDIENCE_DISCRIMINATOR),
]


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
class CustomerBookingResponse(CustomerBookingView):
    """Customer-safe booking contract for the shared routes (discriminated variant)."""

    response_audience: Literal["customer"] = CUSTOMER_AUDIENCE


class InternalBookingResponse(BookingResponse):
    """Full internal booking contract for the shared routes (discriminated variant)."""

    response_audience: Literal["internal"] = INTERNAL_AUDIENCE


BookingAudienceResponse = Annotated[
    CustomerBookingResponse | InternalBookingResponse,
    Field(discriminator=AUDIENCE_DISCRIMINATOR),
]


# --------------------------------------------------------------------------- #
# Payment
# --------------------------------------------------------------------------- #
class CustomerPaymentResponse(CustomerPaymentStatusView):
    """Customer-safe payment-status contract for the shared routes (variant)."""

    response_audience: Literal["customer"] = CUSTOMER_AUDIENCE


class InternalPaymentResponse(PaymentResponse):
    """Full internal payment contract for the shared routes (discriminated variant)."""

    response_audience: Literal["internal"] = INTERNAL_AUDIENCE


PaymentAudienceResponse = Annotated[
    CustomerPaymentResponse | InternalPaymentResponse,
    Field(discriminator=AUDIENCE_DISCRIMINATOR),
]


__all__ = [
    "AUDIENCE_DISCRIMINATOR",
    "CUSTOMER_AUDIENCE",
    "INTERNAL_AUDIENCE",
    "CustomerOfferResponse",
    "InternalOfferResponse",
    "OfferAudienceResponse",
    "CustomerBookingResponse",
    "InternalBookingResponse",
    "BookingAudienceResponse",
    "CustomerPaymentResponse",
    "InternalPaymentResponse",
    "PaymentAudienceResponse",
]
