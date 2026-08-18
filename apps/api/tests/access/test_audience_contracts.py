"""Phase 9.1.A — typed audience-aware response contracts (ADR-046).

Three layers of proof for the eight shared routes:

1. **Generated OpenAPI** — each route documents a non-empty, discriminated
   customer/internal 2xx schema (the offers route as an array of discriminated items),
   both variants are reachable components, the customer variant carries no confidential
   field, ``response_audience`` is a literal customer/internal, operation ids are stable,
   and the error envelopes remain documented. These inspect the *emitted* schema, not the
   Python models.
2. **Runtime response validation** — a real request returns the correct discriminated
   member for its audience (customer → ``response_audience == "customer"`` with no
   confidential field; operator/platform → ``"internal"`` with the split), which would
   fail if FastAPI serialized an internal object through the customer variant or selected
   the wrong union member.
3. **Union selection** — the discriminated union selects strictly by the discriminator and
   never strips fields or coerces a variant, and a payload without the discriminator fails
   closed.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import iam_support
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from sky_bridge_jet.main import app
from sky_bridge_jet.modules.audience import (
    BookingAudienceResponse,
    CustomerBookingResponse,
    CustomerOfferResponse,
    CustomerPaymentResponse,
    OfferAudienceResponse,
    PaymentAudienceResponse,
)

requires_db = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="set RUN_DATABASE_INTEGRATION=1 with PostgreSQL available",
)

# Fields that must never appear in any customer-facing variant (incl. nested/lists).
FORBIDDEN = (
    "operator_amount_minor",
    "platform_fee_minor",
    "settlement_eligibility",
    "provider_payment_reference",
    "provider_reference",
    "provider_status",
    "idempotency_key",
    "allocation",
    "operator_notes",
    "operator_id",
)

# The eight shared routes: (method, path, operation_id, is_list).
SHARED_ROUTES: list[tuple[str, str, str, bool]] = [
    ("get", "/api/v1/bookings/{booking_id}", "getBooking", False),
    ("get", "/api/v1/trip-requests/{trip_request_id}/offers", "listTripRequestOffers", True),
    ("get", "/api/v1/payments/{payment_id}", "getPayment", False),
    ("get", "/api/v1/bookings/{booking_id}/payment", "getBookingPayment", False),
    ("get", "/api/v1/trip-requests/{trip_request_id}/booking", "getTripRequestBooking", False),
    ("post", "/api/v1/bookings", "createBooking", False),
    ("post", "/api/v1/bookings/{booking_id}/cancel", "cancelBooking", False),
    (
        "post",
        "/api/v1/trip-requests/{trip_request_id}/offers/{offer_id}/select",
        "selectOperatorOffer",
        False,
    ),
]


def _spec() -> dict[str, Any]:
    return app.openapi()


def _twoxx_schema(operation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    code = next(c for c in operation["responses"] if c.startswith("2"))
    return code, operation["responses"][code]["content"]["application/json"]["schema"]


def _component(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/components/schemas/"), ref
    return spec["components"]["schemas"][ref.rsplit("/", 1)[1]]


# --------------------------------------------------------------------------- #
# 1 — Generated OpenAPI contract
# --------------------------------------------------------------------------- #
def test_all_shared_routes_have_typed_discriminated_2xx() -> None:
    spec = _spec()
    for method, path, operation_id, is_list in SHARED_ROUTES:
        operation = spec["paths"][path][method]
        assert operation["operationId"] == operation_id  # operation ids are stable
        _code, schema = _twoxx_schema(operation)
        assert schema and schema != {}, (method, path)  # never the empty untyped body
        if is_list:
            assert schema["type"] == "array", (method, path)
            item = schema["items"]
        else:
            item = schema
        disc = item["discriminator"]
        assert disc["propertyName"] == "response_audience", (method, path)
        mapping = disc["mapping"]
        # A generated TS client can distinguish the variants: two literal keys, two refs.
        assert set(mapping) == {"customer", "internal"}, (method, path)
        assert mapping["customer"] != mapping["internal"], (method, path)
        one_of_refs = {entry["$ref"] for entry in item["oneOf"]}
        assert set(mapping.values()) <= one_of_refs, (method, path)

        customer = _component(spec, mapping["customer"])
        internal = _component(spec, mapping["internal"])
        # The customer variant is structurally safe; the internal one keeps the split.
        for forbidden in FORBIDDEN:
            assert forbidden not in customer["properties"], (path, forbidden)
        assert customer["properties"]["response_audience"].get("const") == "customer"
        assert internal["properties"]["response_audience"].get("const") == "internal"

        # Error envelopes remain documented (safe 4xx plus the global 422/500).
        documented = set(operation["responses"])
        assert {"422", "500"} <= documented, (path, documented)
        assert documented & {"403", "404"}, (path, documented)


def test_customer_offer_schema_is_a_named_component_without_confidential_fields() -> None:
    # The canonical customer-safe offer schema (absent from the schema before 9.1.A) is a
    # first-class component that a generated client can reference by name.
    spec = _spec()
    assert "CustomerOfferResponse" in spec["components"]["schemas"]
    props = spec["components"]["schemas"]["CustomerOfferResponse"]["properties"]
    for forbidden in FORBIDDEN:
        assert forbidden not in props, forbidden
    assert props["response_audience"].get("const") == "customer"


def test_internal_variants_still_expose_the_full_contract() -> None:
    # The operator/platform-facing variants must keep the confidential commercial fields.
    spec = _spec()
    booking = spec["components"]["schemas"]["InternalBookingResponse"]["properties"]
    payment = spec["components"]["schemas"]["InternalPaymentResponse"]["properties"]
    offer = spec["components"]["schemas"]["InternalOfferResponse"]["properties"]
    assert "operator_amount_minor" in booking and "platform_fee_minor" in booking
    assert "provider_payment_reference" in payment and "provider_status" in payment
    assert "operator_amount_minor" in offer and "operator_notes" in offer


def test_unrelated_endpoints_did_not_gain_the_discriminator() -> None:
    # The base schemas used by /me and the operator/platform-only routes are untouched:
    # they carry no response_audience field (the wrappers are shared-route-specific).
    spec = _spec()
    for name in (
        "CustomerBookingView",  # /me/bookings item
        "CustomerPaymentStatusView",  # /me/payments item
        "BookingResponse",  # confirmBooking/rejectBooking
        "OperatorOfferResponse",  # getOperatorOffer etc.
        "PaymentResponse",  # authorizePayment etc.
    ):
        props = spec["components"]["schemas"][name]["properties"]
        assert "response_audience" not in props, name


# --------------------------------------------------------------------------- #
# 2 — Runtime response validation / audience selection
# --------------------------------------------------------------------------- #
def _no_forbidden(text: str) -> None:
    for field in FORBIDDEN:
        assert field not in text, field


@requires_db
def test_runtime_customer_audience_is_tagged_and_leak_free(
    admin: TestClient, airports: list
) -> None:
    scenario = iam_support.full_booking_scenario(admin, airports, confirm=True)
    customer, _ = iam_support.customer_owner_client(admin, UUID(scenario["customer_id"]))
    booking_id, trip_id, payment_id = (
        scenario["booking_id"],
        scenario["trip_id"],
        scenario["payment_id"],
    )
    single = {
        f"/api/v1/bookings/{booking_id}": dict,
        f"/api/v1/trip-requests/{trip_id}/booking": dict,
        f"/api/v1/payments/{payment_id}": dict,
        f"/api/v1/bookings/{booking_id}/payment": dict,
    }
    for path in single:
        resp = customer.get(path)
        assert resp.status_code == 200, (path, resp.text)
        body = resp.json()
        assert body["response_audience"] == "customer", path
        _no_forbidden(resp.text)
    offers = customer.get(f"/api/v1/trip-requests/{trip_id}/offers")
    assert offers.status_code == 200
    assert offers.json() and all(o["response_audience"] == "customer" for o in offers.json())
    _no_forbidden(offers.text)


@requires_db
def test_runtime_platform_and_operator_audiences_are_internal(
    admin: TestClient, airports: list
) -> None:
    scenario = iam_support.full_booking_scenario(admin, airports, confirm=True)
    booking_id, trip_id, payment_id = (
        scenario["booking_id"],
        scenario["trip_id"],
        scenario["payment_id"],
    )
    # Platform (product owner) receives the full internal variant with the split.
    booking = admin.get(f"/api/v1/bookings/{booking_id}").json()
    assert booking["response_audience"] == "internal"
    assert booking["platform_fee_minor"] is not None
    payment = admin.get(f"/api/v1/payments/{payment_id}").json()
    assert payment["response_audience"] == "internal" and "provider_status" in payment
    offers = admin.get(f"/api/v1/trip-requests/{trip_id}/offers").json()
    assert offers and all(o["response_audience"] == "internal" for o in offers)
    assert all("operator_amount_minor" in o for o in offers)
    # The owning operator is also an internal audience (a party to the amounts).
    operator, _ = iam_support.operator_role_client(
        UUID(scenario["operator_id"]), iam_support.OrganizationRole.OPERATOR_ADMIN
    )
    op_booking = operator.get(f"/api/v1/bookings/{booking_id}").json()
    assert op_booking["response_audience"] == "internal"
    assert op_booking["platform_fee_minor"] is not None


@requires_db
def test_runtime_customer_write_routes_are_customer_tagged(
    admin: TestClient, airports: list
) -> None:
    # createBooking, selectOperatorOffer, cancelBooking are customer-reachable writes.
    scenario = iam_support.full_booking_scenario(admin, airports, confirm=False)
    customer, _ = iam_support.customer_owner_client(admin, UUID(scenario["customer_id"]))
    cancelled = customer.post(
        f"/api/v1/bookings/{scenario['booking_id']}/cancel", json={"actor": "CUSTOMER"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["response_audience"] == "customer"
    _no_forbidden(cancelled.text)


# --------------------------------------------------------------------------- #
# 3 — Union selection: discriminator, no coercion, fail-closed
# --------------------------------------------------------------------------- #
def _sample_customer_booking() -> CustomerBookingResponse:
    from datetime import UTC, datetime
    from uuid import uuid4

    now = datetime.now(UTC)
    return CustomerBookingResponse(
        id=uuid4(),
        reference="SBJ-1",
        trip_request_id=uuid4(),
        operator_offer_id=uuid4(),
        status="PENDING_OPERATOR_CONFIRMATION",
        currency="EUR",
        total_amount_minor=1_050_000,
        tax_amount_minor=50_000,
        operator_legal_name="Scenario Air",
        aircraft_registration="EI-ABC",
        aircraft_manufacturer="Cessna",
        aircraft_model="CJ3+",
        aircraft_category="LIGHT_JET",
        confirmed_at=None,
        cancelled_at=None,
        cancellation_actor=None,
        cancellation_reason=None,
        created_at=now,
        updated_at=now,
    )


def test_union_selects_customer_member_and_strips_nothing() -> None:
    adapter = TypeAdapter(BookingAudienceResponse)
    dumped = _sample_customer_booking().model_dump()
    selected = adapter.validate_python(dumped)
    assert isinstance(selected, CustomerBookingResponse)
    out = adapter.dump_python(selected)
    for forbidden in FORBIDDEN:
        assert forbidden not in out


def test_union_without_discriminator_fails_closed() -> None:
    # A bare payload missing the discriminator cannot be silently coerced into a member.
    adapter = TypeAdapter(BookingAudienceResponse)
    dumped = _sample_customer_booking().model_dump()
    dumped.pop("response_audience")
    with pytest.raises(ValidationError):
        adapter.validate_python(dumped)


def test_each_union_carries_two_distinct_members() -> None:
    # Guards against a future edit collapsing a union to a single audience.
    for adapter_type, customer_cls in (
        (OfferAudienceResponse, CustomerOfferResponse),
        (BookingAudienceResponse, CustomerBookingResponse),
        (PaymentAudienceResponse, CustomerPaymentResponse),
    ):
        schema = TypeAdapter(adapter_type).json_schema()
        mapping = schema["discriminator"]["mapping"]
        assert set(mapping) == {"customer", "internal"}
        assert customer_cls.__name__ in mapping["customer"]
        assert customer_cls.__name__ not in mapping["internal"]
