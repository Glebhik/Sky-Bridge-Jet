# ADR-045: Customer-safe read models and audience-aware serialization (Phase 9.0.B)

## Status

Accepted (Phase 9.0.B). Removes the temporary customer-read restriction of ADR-041. No
schema change, no migration.

## Context

Phase 9.0.A-1 (ADR-041) temporarily denied ordinary customers the offer/booking/payment
reads because those responses expose the internal operator/platform commercial split.
Phase 9.0.B introduces dedicated customer-safe projections so a customer can safely read
its own resources, and closes the pre-existing leaks where a customer *mutation* returned
a full internal object.

## Decision

**Distinct customer-safe schemas** (`modules/customer_views.py`): `CustomerOfferView`,
`CustomerBookingView`, `CustomerPaymentStatusView`. Each contains only customer-visible
fields (total customer price, tax, currency, status, validity/timestamps, aircraft/operator
display), and **structurally omits** the forbidden fields — never present, not merely null,
even in nested objects or lists:

- `operator_amount_minor`, `platform_fee_minor` (the operator/platform split);
- allocation, settlement eligibility, reconciliation data;
- provider references / provider status / raw `PaymentOperation` history;
- idempotency keys; platform-only notes; internal review/audit metadata; secrets/tokens.

The full internal `OperatorOfferResponse` / `BookingResponse` / `PaymentResponse` schemas
are unchanged and remain the response on operator/platform-audience routes.

**Audience-aware serialization (server-side).** Shared routes authorize first, then select
the schema by audience determined server-side (`access.is_customer_view(principal,
owner_customer_id)` — true only for a principal that owns the customer tenant). The
handler builds and returns the customer view for a customer and the full internal model
for operator/platform, using `response_model=None` so each audience's actual schema is
serialized — never a union in which a forbidden field could appear in the customer branch,
and never frontend field-hiding. Affected routes: `GET /trip-requests/{id}/offers`,
`POST /trip-requests/{id}/offers/{offer_id}/select`, `POST /bookings`,
`GET /bookings/{id}`, `POST /bookings/{id}/cancel`, `GET /trip-requests/{id}/booking`,
`GET /payments/{id}`, `GET /bookings/{id}/payment`. The owning customer is now allowed
(safe view) where ADR-041 temporarily returned 403; cross-tenant remains 404; platform
reads remain audited; operator/platform lifecycle and confirm/reject are unchanged.

**Customer "my" list endpoints.** Three read-only, customer-scoped endpoints are added:
`GET /me/trip-requests`, `GET /me/bookings`, `GET /me/payments`. The active CUSTOMER
organization is resolved and validated server-side (Phase 9.0.A-1 policy); the canonical
`customer_id` comes from that organization — never the client. Queries **filter by tenant
in SQL before materialization** over the canonical joins
(`TripRequest.customer_id`; `Booking → TripRequest`; `Payment → Booking → TripRequest`),
use deterministic ordering (`created_at desc, id`), and are bounded by pagination
(`limit` 1–100 default 20, `offset ≥ 0`). A platform/operator principal without a customer
context receives 403; a customer never receives another customer's row.

**Payment status vs. initiation.** The customer payment view is **status only** — payment
ID, booking ID, status, currency, total/authorized/captured amounts, and the *aggregate*
refunded amount. Customers get no allocation, no refund list
(`GET /payments/{id}/allocation`, `/refunds` stay platform-read-only per ADR-043), and no
payment operational command (create/authorize/capture/void/refund stay denied).

## Consequences

Customers can now read and list their own offers, bookings, and payment status safely; no
customer response contains an internal/operator/platform field (proven by negative contract
tests, including nested objects and list items); operator/platform responses and the
Phase 9.0.A-3 payment protections are unchanged. Customer self-provisioning is ADR-044.
Frontend, profile editing, and the organization selector are Phase 9.1.
