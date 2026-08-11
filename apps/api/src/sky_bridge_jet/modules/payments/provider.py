from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProviderOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProviderResult:
    """Provider-neutral result. Raw provider exceptions never cross this boundary."""

    outcome: ProviderOutcome
    provider_reference: str | None
    failure_code: str | None = None


class PaymentProvider(Protocol):
    """Provider-neutral payment port.

    A future licensed-PSP adapter implements these capabilities without changing
    the payment domain. It must return typed results and must not leak raw
    provider exceptions.
    """

    def authorize(
        self, *, amount_minor: int, currency: str, payment_method_reference: str | None
    ) -> ProviderResult: ...

    def capture(
        self, *, provider_reference: str, amount_minor: int, currency: str
    ) -> ProviderResult: ...

    def void(self, *, provider_reference: str) -> ProviderResult: ...

    def refund(
        self, *, provider_reference: str, amount_minor: int, currency: str
    ) -> ProviderResult: ...


# Deterministic test selectors interpreted only by the fake adapter. A real PSP
# adapter would ignore these and use a tokenized payment method from PSP-hosted
# fields. They are transient inputs and are never persisted.
DECLINE_AUTHORIZATION = "decline-authorization"
DECLINE_CAPTURE = "decline-capture"
DECLINE_REFUND = "decline-refund"

_CAPTURE_FAIL_MARKER = "CAPFAIL"
_REFUND_FAIL_MARKER = "REFFAIL"


class FakePaymentProvider:
    """A deterministic, in-process fake. NOT A PRODUCTION INTEGRATION.

    It moves no money and makes no external call. Test outcomes are selected by
    sentinel ``payment_method_reference`` values; the chosen behaviour for later
    capture/refund is encoded into the returned authorization reference so the
    adapter stays stateless.
    """

    def _reference(self, marker: str) -> str:
        return f"fauth_{marker}_{secrets.token_hex(8)}"

    def authorize(
        self, *, amount_minor: int, currency: str, payment_method_reference: str | None
    ) -> ProviderResult:
        if payment_method_reference == DECLINE_AUTHORIZATION:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=None,
                failure_code="authorization_declined",
            )
        if payment_method_reference == DECLINE_CAPTURE:
            reference = self._reference(_CAPTURE_FAIL_MARKER)
        elif payment_method_reference == DECLINE_REFUND:
            reference = self._reference(_REFUND_FAIL_MARKER)
        else:
            reference = self._reference("OK")
        return ProviderResult(outcome=ProviderOutcome.SUCCEEDED, provider_reference=reference)

    def capture(
        self, *, provider_reference: str, amount_minor: int, currency: str
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

    def void(self, *, provider_reference: str) -> ProviderResult:
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_reference=provider_reference.replace("fauth", "fvoid", 1),
        )

    def refund(
        self, *, provider_reference: str, amount_minor: int, currency: str
    ) -> ProviderResult:
        if _REFUND_FAIL_MARKER in provider_reference:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_reference=provider_reference,
                failure_code="refund_declined",
            )
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_reference=f"fref_{secrets.token_hex(8)}",
        )


def get_payment_provider() -> PaymentProvider:
    """Return the active payment provider.

    Phase 5 has no real PSP integration, so the deterministic fake is always
    used. A future phase selects a licensed provider adapter here behind the same
    port.
    """
    return FakePaymentProvider()
