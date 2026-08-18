# ADR-046: Typed audience-aware API response contracts (Phase 9.1.A)

## Status

Accepted (Phase 9.1.A). Restores validated, accurately documented contracts on the eight
shared resource routes that Phase 9.0.B served with `response_model=None`. No schema
change, no migration. Supersedes the temporary untyped-contract note in ADR-045.

## Context

Phase 9.0.B (ADR-045) made eight routes audience-aware: the owning customer receives a
customer-safe projection while an owning operator or an authorized platform actor receives
the full internal model. It implemented that split at runtime by returning one of two
distinct schemas and declaring `response_model=None`. That was confidential-safe at
runtime but left two gaps flagged in the PR #15 audit:

- the generated OpenAPI 2xx body for all eight routes was the empty schema `{}`, so a
  generated TypeScript client could not represent the response and `CustomerOfferView`
  appeared in no component;
- FastAPI response-model validation was disabled on those routes.

The eight routes:

| Method | Path | operation_id |
| --- | --- | --- |
| GET | `/bookings/{id}` | `getBooking` |
| GET | `/trip-requests/{id}/offers` | `listTripRequestOffers` |
| GET | `/payments/{id}` | `getPayment` |
| GET | `/bookings/{id}/payment` | `getBookingPayment` |
| GET | `/trip-requests/{id}/booking` | `getTripRequestBooking` |
| POST | `/bookings` | `createBooking` |
| POST | `/bookings/{id}/cancel` | `cancelBooking` |
| POST | `/trip-requests/{id}/offers/{offer_id}/select` | `selectOperatorOffer` |

## Decision

**Discriminated audience unions.** Each shared route's `response_model` is a discriminated
`Union` of two structural variants tagged by a required literal `response_audience`
(`"customer"` / `"internal"`), declared with Pydantic `Field(discriminator=
"response_audience")`. The offers collection route keeps its **top-level array** and uses
`list[…]` of the discriminated item union; no response becomes an envelope object and no
`/me` list-item contract changes.

**Shared-route-specific wrapper models** (`modules/audience.py`):

- `CustomerOfferResponse` / `CustomerBookingResponse` / `CustomerPaymentResponse` subclass
  the Phase 9.0.B customer-safe views (`CustomerOfferView`, `CustomerBookingView`,
  `CustomerPaymentStatusView`) and add `response_audience = "customer"`;
- `InternalOfferResponse` / `InternalBookingResponse` / `InternalPaymentResponse` subclass
  the unchanged internal schemas (`OperatorOfferResponse`, `BookingResponse`,
  `PaymentResponse`) and add `response_audience = "internal"`.

Subclassing means the **base schemas are untouched**: the `/me` list items and the
operator/platform-only routes (`getOperatorOffer`, `confirmBooking`, `authorizePayment`, …)
keep their exact contracts and never gain the discriminator. The customer variants remain
**structurally** safe — the operator/platform split, allocation/settlement data, provider
references, raw operations, idempotency keys, and audit metadata cannot appear because the
customer classes have no such fields, even nested. Frontend field-hiding is never a
security control.

**Server-side audience selection, then validated serialization.** The handler authorizes
first, decides the audience with `access.is_customer_view(...)`, and constructs the
matching envelope from the vetted view (`CustomerXResponse.model_validate(customer_x_view
(obj))`) or the internal model. FastAPI validates the returned instance against the union;
because the union is *discriminated*, Pydantic selects the member by the concrete instance's
literal — there is no positional coercion and no silent field stripping. A bare object
lacking the discriminator cannot validate as the customer variant, so a mis-wired handler
fails closed rather than leaking.

## Compatibility impact

Additive and non-breaking: each of the eight responses gains one always-present required
field, `response_audience`. Consumers that ignore unknown fields are unaffected; a
generated client gains an accurate discriminated union. Operation ids are unchanged. The
error envelopes (401/403/404/409 as applicable, plus the global 422/500) remain documented.
`CustomerOfferResponse` — the canonical customer-safe offer schema, absent from the schema
before 9.1.A — is now a named component.

## Alternatives considered

- **Explicit `responses={2xx: {"model": CustomerXView}}` while keeping
  `response_model=None`.** Smaller (no new field) but documents only the customer variant
  and does **not** re-enable response-model validation. Rejected by the PO in favour of the
  fully validated discriminated union.
- **A single union without a discriminator.** Rejected: positional union validation could
  coerce an internal object into the customer branch (or vice versa) and is ambiguous in
  OpenAPI.

## Consequences

All eight routes now emit non-empty, typed, discriminated 2xx schemas (the offers route as
an array of discriminated items); both variants are named components; response validation is
active; and generated TypeScript clients receive a usable discriminated union. Confidential
fields remain structurally impossible in customer responses (proven by OpenAPI negative
tests and runtime audience-tag assertions on real requests). The self-provisioning and
payment-operational protections of ADR-043/044/045 are unchanged. The web client that
consumes these contracts is Phase 9.1.B.
