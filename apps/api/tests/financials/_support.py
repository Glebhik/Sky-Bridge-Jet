"""Shared fakes/builders for Phase 7 Stripe & financial-onboarding tests.

Everything here stays in-process: the Stripe boundary is a deterministic fake, so
these tests need no Stripe network access or credentials. The real adapters
(``StripeConnectPaymentProvider`` / ``StripeConnectFinancialProvider``) are driven
against :class:`FakeStripeGateway` to exercise real mapping logic without the SDK.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sky_bridge_jet.core.config import Settings
from sky_bridge_jet.core.stripe_gateway import (
    StripeAccountLinkView,
    StripeAccountView,
    StripePaymentIntentView,
    StripeRefundView,
    WebhookSignatureError,
)

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

# A verified webhook whose signature header equals this value is accepted by the
# fake gateway; anything else is treated as tampered/unsigned.
VALID_SIGNATURE = "t=1,v1=valid"


def stripe_test_settings(**overrides: Any) -> Settings:
    """Build settings with Stripe enabled in TEST MODE (never a live key)."""
    values: dict[str, Any] = {
        "stripe_enabled": True,
        "stripe_secret_key": "sk_test_example",
        "stripe_webhook_secret": "whsec_test_example",
    }
    values.update(overrides)
    return Settings(**values)


@dataclass
class FakeStripeGateway:
    """In-process StripeGateway. Configurable statuses; no network, no SDK."""

    intent_status: str = "requires_capture"
    capture_status: str = "succeeded"
    cancel_status: str = "canceled"
    refund_status: str = "succeeded"
    client_secret: str | None = "pi_secret_example"
    account: StripeAccountView | None = None
    account_link_url: str = "https://connect.test.invalid/onboarding"
    next_intent_id: str = "pi_test_123"
    expected_signature: str = VALID_SIGNATURE
    calls: list[tuple[str, str]] = field(default_factory=list)

    def _account(self) -> StripeAccountView:
        return self.account or StripeAccountView(
            id="acct_test_123",
            country="IE",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
            requirements_due=False,
            disabled_reason=None,
        )

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_method_reference: str | None,
        idempotency_key: str,
    ) -> StripePaymentIntentView:
        self.calls.append(("create_payment_intent", idempotency_key))
        secret = (
            self.client_secret
            if self.intent_status in {"requires_action", "requires_payment_method"}
            else None
        )
        return StripePaymentIntentView(
            id=self.next_intent_id, status=self.intent_status, client_secret=secret
        )

    def capture_payment_intent(
        self, *, intent_id: str, idempotency_key: str
    ) -> StripePaymentIntentView:
        self.calls.append(("capture_payment_intent", idempotency_key))
        return StripePaymentIntentView(id=intent_id, status=self.capture_status)

    def cancel_payment_intent(
        self, *, intent_id: str, idempotency_key: str
    ) -> StripePaymentIntentView:
        self.calls.append(("cancel_payment_intent", idempotency_key))
        return StripePaymentIntentView(id=intent_id, status=self.cancel_status)

    def create_refund(
        self, *, intent_id: str, amount_minor: int, idempotency_key: str
    ) -> StripeRefundView:
        self.calls.append(("create_refund", idempotency_key))
        return StripeRefundView(id="re_test_123", status=self.refund_status)

    def create_connected_account(self, *, country: str, idempotency_key: str) -> StripeAccountView:
        self.calls.append(("create_connected_account", idempotency_key))
        template = self._account()
        # The stored ``provider_account_reference`` is unique, so each created
        # account gets a fresh id while keeping the configured capability flags.
        return replace(template, id=f"acct_{uuid4().hex}")

    def create_account_link(self, *, account_id: str) -> StripeAccountLinkView:
        self.calls.append(("create_account_link", account_id))
        return StripeAccountLinkView(url=self.account_link_url, expires_at=0)

    def retrieve_account(self, *, account_id: str) -> StripeAccountView:
        self.calls.append(("retrieve_account", account_id))
        return self._account()

    def construct_webhook_event(
        self, *, payload: bytes, signature_header: str | None, webhook_secret: str
    ) -> Any:
        # Mirror the real gateway: reject missing/invalid signatures before any
        # normalization. The raw body is required and verified.
        if not signature_header:
            raise WebhookSignatureError("Missing webhook signature")
        if signature_header != self.expected_signature:
            raise WebhookSignatureError("Invalid webhook signature")
        from sky_bridge_jet.core.stripe_gateway import StripeEventView

        event = json.loads(payload.decode("utf-8"))
        data_object = (event.get("data") or {}).get("object") or {}
        return StripeEventView(
            id=event["id"],
            type=event["type"],
            object_id=data_object.get("id"),
            data=dict(data_object),
        )


ENABLED_ACCOUNT = StripeAccountView(
    id="acct_enabled",
    country="IE",
    charges_enabled=True,
    payouts_enabled=True,
    details_submitted=True,
    requirements_due=False,
    disabled_reason=None,
)

REQUIREMENTS_DUE_ACCOUNT = StripeAccountView(
    id="acct_pending",
    country="IE",
    charges_enabled=False,
    payouts_enabled=False,
    details_submitted=False,
    requirements_due=True,
    disabled_reason=None,
)


def signed_event(event_id: str, event_type: str, object_id: str, **extra: Any) -> bytes:
    """Serialize a minimal Stripe-shaped event body for the fake gateway."""
    obj: dict[str, Any] = {"id": object_id, **extra}
    return json.dumps({"id": event_id, "type": event_type, "data": {"object": obj}}).encode("utf-8")


# -- Aviation booking builders (self-contained; mirrors the payments suite) ------

_REVIEWER = {"actor_type": "PLATFORM_REVIEWER"}


def _future_iso(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _eligibility_expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=365)).isoformat()


def make_operator_eligible(client: TestClient, operator_id: str, aircraft_id: str) -> None:
    """Admit the operator and authorize the aircraft (Phase 6 aviation eligibility)."""
    if client.get(f"/api/v1/operators/{operator_id}/admission").status_code != 200:
        client.post(f"/api/v1/operators/{operator_id}/admission")
        client.post(f"/api/v1/operators/{operator_id}/admission/submit")
        client.post(
            f"/api/v1/operators/{operator_id}/admission/review",
            json={"action": "APPROVE", **_REVIEWER},
        )
        for body in (
            {
                "evidence_type": "OPERATING_AUTHORITY",
                "reference_number": "AOC-1",
                "issuing_authority": "IAA",
                "jurisdiction": "IE",
                "expiry_date": _eligibility_expiry(),
            },
            {
                "evidence_type": "INSURANCE",
                "insurer_name": "Acme",
                "reference_number": "POL-1",
                "expiry_date": _eligibility_expiry(),
            },
        ):
            evidence = client.post(f"/api/v1/operators/{operator_id}/evidence", json=body).json()
            client.post(
                f"/api/v1/evidence/{evidence['id']}/review",
                json={"action": "VERIFY", **_REVIEWER},
            )
    if (
        client.get(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization"
        ).status_code
        != 200
    ):
        client.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization",
            json={"authority_basis": "OWNED"},
        )
        client.post(f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/submit")
        client.post(
            f"/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review",
            json={"action": "APPROVE", **_REVIEWER},
        )


def booking_scenario(
    client: TestClient,
    airports: list[dict[str, Any]],
    *,
    confirm: bool = True,
    operator_amount_minor: int = 1_000_000,
    tax_amount_minor: int = 50_000,
) -> dict[str, Any]:
    """Build customer→operator→aircraft→trip→selected offer→booking."""
    customer = client.post(
        "/api/v1/customers",
        json={
            "customer_type": "INDIVIDUAL",
            "display_name": "Fin Customer",
            "primary_email": f"fincust-{uuid4()}@example.test",
            "preferred_currency": "EUR",
            "timezone": "Europe/Dublin",
        },
    ).json()
    operator = client.post(
        "/api/v1/operators",
        json={
            "legal_name": f"Fin Aviation {uuid4()}",
            "country_code": "IE",
            "contact_email": f"finops-{uuid4()}@example.test",
        },
    ).json()
    aircraft = client.post(
        "/api/v1/aircraft",
        json={
            "operator_id": operator["id"],
            "manufacturer": "Cessna",
            "model": "Citation CJ3+",
            "category": "LIGHT_JET",
            "registration": f"EI-{uuid4().hex[:6].upper()}",
            "passenger_capacity": 7,
        },
    ).json()
    make_operator_eligible(client, operator["id"], aircraft["id"])
    trip = client.post(
        "/api/v1/trip-requests",
        json={
            "customer_id": customer["id"],
            "legs": [
                {
                    "origin_airport_id": airports[0]["id"],
                    "destination_airport_id": airports[1]["id"],
                    "departure_at": "2026-12-01T14:00:00+00:00",
                    "passenger_count": 2,
                }
            ],
        },
    ).json()
    client.post(
        f"/api/v1/trip-requests/{trip['id']}/submit", json={"expected_version": trip["version"]}
    )
    offer = client.post(
        "/api/v1/offers",
        json={
            "trip_request_id": trip["id"],
            "operator_id": operator["id"],
            "aircraft_id": aircraft["id"],
            "currency": "EUR",
            "operator_amount_minor": operator_amount_minor,
            "tax_amount_minor": tax_amount_minor,
            "valid_until": _future_iso(),
        },
    ).json()
    client.post(f"/api/v1/offers/{offer['id']}/submit")
    client.post(f"/api/v1/trip-requests/{trip['id']}/offers/{offer['id']}/select")
    booking = client.post(
        "/api/v1/bookings",
        json={"trip_request_id": trip["id"], "operator_offer_id": offer["id"]},
    ).json()
    if confirm:
        confirmed = client.post(
            f"/api/v1/bookings/{booking['id']}/confirm", json={"operator_id": operator["id"]}
        )
        assert confirmed.status_code == 200, confirmed.text
        booking = confirmed.json()
    return {"customer": customer, "operator": operator, "booking": booking}
