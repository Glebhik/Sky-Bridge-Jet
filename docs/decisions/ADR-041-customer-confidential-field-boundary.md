# ADR-041: Customer confidential-field boundary (temporary read restriction)

## Status

Accepted (Phase 9.0.A-1). The customer-safe projections are owned by Phase 9.0.B.

## Context

The existing `OperatorOfferResponse`, `BookingResponse`, and `PaymentResponse` expose
`operator_amount_minor` and `platform_fee_minor` — the internal operator/platform
commercial split, which a customer must never see. Phase 9.0.A-1's mandate is to
*close the security debt* with the smallest change, not to build the Customer Portal's
read models (that is Phase 9.0.B).

## Decision

For the customer-reachable reads whose response still leaks confidential fields —
`GET /trip-requests/{id}/offers`, `GET /bookings/{id}`,
`GET /trip-requests/{id}/booking`, `GET /payments/{id}`,
`GET /bookings/{id}/payment` — this PR **enforces ownership** and **serves the full
response only to a platform viewer**. An owning customer receives a temporary 403
(the resource is theirs, but no customer-safe view exists yet); any other principal or
cross-tenant probe receives 404.

This closes the leak without inventing new customer read models: no customer ever
receives a body containing `platform_fee_minor` / `operator_amount_minor`. The
approved customer-safe projections (total customer price, tax, currency, validity,
permitted aircraft/operator display, safe payment status, customer-paid/refunded
totals) are introduced in Phase 9.0.B (D3), at which point the customer 403 becomes a
200 over the safe schema. Confidentiality is enforced server-side; the frontend is
never relied upon to hide fields.

## Consequences

The security boundary is correct now (deny beats leak), and the customer read
experience is enabled later behind a dedicated, tested projection. Negative tests
assert customers never receive the confidential fields.
