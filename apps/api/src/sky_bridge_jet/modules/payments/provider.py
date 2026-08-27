from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sky_bridge_jet.modules.payments.domain import PaymentProviderKind


class ProviderOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    # The customer must complete an action (e.g. 3-D Secure) before the provider
    # can finalize the operation. The domain treats this as a distinct state.
    REQUIRES_ACTION = "REQUIRES_ACTION"


class ProviderErrorCategory(StrEnum):
    """Stable, provider-neutral categories for provider failures."""

    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_DECLINED = "PROVIDER_DECLINED"
    PROVIDER_REQUIRES_ACTION = "PROVIDER_REQUIRES_ACTION"
    PROVIDER_INVALID_STATE = "PROVIDER_INVALID_STATE"
    PROVIDER_CONFIGURATION_ERROR = "PROVIDER_CONFIGURATION_ERROR"
    PROVIDER_AUTHENTICATION_ERROR = "PROVIDER_AUTHENTICATION_ERROR"


class PaymentProviderError(Exception):
    """Raised by an adapter for infrastructure failures; never leaks raw provider data."""

    def __init__(
        self, category: ProviderErrorCategory, message: str = "A payment provider error occurred"
    ) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ClientAction:
    """Transient browser-required client action for a customer to complete (SCA).

    The ``client_secret`` is required by the provider's client SDK to complete the
    action; it is returned once to the client and never persisted or logged.
    """

    action_type: str
    client_secret: str


@dataclass(frozen=True)
class ProviderResult:
    """Provider-neutral result. Raw provider exceptions never cross this boundary."""

    outcome: ProviderOutcome
    provider_reference: str | None
    failure_code: str | None = None
    provider_status: str | None = None
    client_action: ClientAction | None = None


class PaymentProvider(Protocol):
    """Provider-neutral payment port.

    A future licensed-PSP adapter implements these capabilities without changing
    the payment domain. It must return typed results and must not leak raw
    provider exceptions.
    """

    kind: PaymentProviderKind

    def authorize(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_reference: str | None,
        idempotency_key: str,
    ) -> ProviderResult: ...

    def capture(
        self, *, provider_reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> ProviderResult: ...

    def void(self, *, provider_reference: str, idempotency_key: str) -> ProviderResult: ...

    def refund(
        self, *, provider_reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> ProviderResult: ...


# Deterministic test selectors interpreted only by the fake adapter. A real PSP
# adapter would ignore these and use a tokenized payment method from PSP-hosted
# fields. They are transient inputs and are never persisted.
DECLINE_AUTHORIZATION = "decline-authorization"
DECLINE_CAPTURE = "decline-capture"
DECLINE_CAPTURE_AND_VOID = "decline-capture-and-void"
DECLINE_VOID = "decline-void"
DECLINE_REFUND = "decline-refund"

_CAPTURE_FAIL_MARKER = "CAPFAIL"
_VOID_FAIL_MARKER = "VOIDFAIL"
_REFUND_FAIL_MARKER = "REFFAIL"


class FakePaymentProvider:
    """A deterministic, in-process fake. NOT A PRODUCTION INTEGRATION.

    It moves no money and makes no external call. Test outcomes are selected by
    sentinel ``payment_method_reference`` values; the chosen behaviour for later
    capture/refund is encoded into the returned authorization reference so the
    adapter stays stateless.
    """

    kind = PaymentProviderKind.FAKE

    def _reference(self, marker: str, idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        return f"fauth_{marker}_{digest}"

    def authorize(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_reference: str | None,
        idempotency_key: str,
    ) -> ProviderResult:
        if payment_method_reference == DECLINE_AUTHORIZATION:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=None,
                failure_code="authorization_declined",
            )
        if payment_method_reference == DECLINE_CAPTURE:
            reference = self._reference(_CAPTURE_FAIL_MARKER, idempotency_key)
        elif payment_method_reference == DECLINE_CAPTURE_AND_VOID:
            reference = self._reference(
                f"{_CAPTURE_FAIL_MARKER}_{_VOID_FAIL_MARKER}", idempotency_key
            )
        elif payment_method_reference == DECLINE_VOID:
            reference = self._reference(_VOID_FAIL_MARKER, idempotency_key)
        elif payment_method_reference == DECLINE_REFUND:
            reference = self._reference(_REFUND_FAIL_MARKER, idempotency_key)
        else:
            reference = self._reference("OK", idempotency_key)
        return ProviderResult(outcome=ProviderOutcome.SUCCEEDED, provider_reference=reference)

    def capture(
        self, *, provider_reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> ProviderResult:
        if _CAPTURE_FAIL_MARKER in provider_reference:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=provider_reference,
                failure_code="capture_declined",
            )
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_reference=provider_reference.replace("fauth", "fcap", 1),
        )

    def void(self, *, provider_reference: str, idempotency_key: str) -> ProviderResult:
        if _VOID_FAIL_MARKER in provider_reference:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=provider_reference,
                failure_code="void_declined",
            )
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_reference=provider_reference.replace("fauth", "fvoid", 1),
        )

    def refund(
        self, *, provider_reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> ProviderResult:
        if _REFUND_FAIL_MARKER in provider_reference:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=provider_reference,
                failure_code="refund_declined",
            )
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_reference=f"fref_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}",
        )


def get_payment_provider() -> PaymentProvider:
    """Return the active payment provider.

    Phase 5 has no real PSP integration, so the deterministic fake is always
    used. A future phase selects a licensed provider adapter here behind the same
    port.
    """
    return FakePaymentProvider()
