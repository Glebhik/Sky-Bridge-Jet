# Phase 9.0.B — Customer Provisioning and Safe Read Models

## Purpose

The Phase 9.0.B delivery unit is the **backend foundation** for the future Customer
Portal — not the portal UI. It adds: atomic customer self-provisioning after verified
registration; customer-scoped "my" list endpoints; customer-safe offer/booking/payment
projections; and audience-aware serialization that removes the temporary Phase 9.0.A-1
customer-read restriction while preserving all operator/platform behavior. No frontend,
no live payments, no schema change, no migration.

## Customer self-provisioning (ADR-044)

On email verification a normal self-registering individual is atomically provisioned one
`Customer` + one CUSTOMER `Organization` + one active `CUSTOMER_OWNER` membership, inside
the verification transaction (which already locks the user row). The client supplies no
identity or role. Provisioning is **skipped** when a higher-precedence path applies:

- user not `ACTIVE` (suspended/disabled never provisions);
- user already has an active membership;
- a valid pending invitation exists for the email (invitation path is authoritative).

The single-use token + user row-lock make it idempotent and concurrency-safe (at most one
tenant under concurrent/repeated verification). The required display name is a neutral
placeholder `"Personal account"` (provisional, never a company name or email-derived). A
successful provisioning writes one append-only `customer_self_provisioned` audit record
(user id + new org id only; no tokens/PII). `POST /customers` stays platform-admin only.

## Active customer context (unchanged from 9.0.A-1)

One eligible CUSTOMER org auto-resolves; multiple require a validated `X-Organization-Id`;
the org must be an active CUSTOMER membership of the principal; `customer_id` comes from
the validated org; switching orgs never reuses another tenant's data. The frontend
selector is Phase 9.1.

## Customer "my" list endpoints (3 → PHASE_9_0B_BOUND)

| Route | Response | Rule |
| --- | --- | --- |
| `GET /me/trip-requests` | `list[TripRequestResponse]` | own trips; `TripRequest.customer_id` |
| `GET /me/bookings` | `list[CustomerBookingView]` | own bookings; `Booking → TripRequest` |
| `GET /me/payments` | `list[CustomerPaymentStatusView]` | own payments; `Payment → Booking → TripRequest` |

Active CUSTOMER org resolved server-side; `customer_id` never from the client; **SQL-filtered
by tenant before materialization**; deterministic order (`created_at desc, id`); bounded
pagination (`limit` 1–100 default 20, `offset ≥ 0`); safe empty collections; a
platform/operator principal without a customer context gets 403.

## Customer-safe projections (ADR-045)

Distinct schemas `CustomerOfferView` / `CustomerBookingView` / `CustomerPaymentStatusView`
contain only customer-visible fields and **structurally omit** the forbidden ones
(operator_amount_minor, platform_fee_minor, allocation, settlement, reconciliation,
provider references, raw operations, idempotency keys, platform notes, audit metadata).

Audience-aware serialization on shared routes: authorize first, then select the schema by
server-side audience (`is_customer_view`) — customer → safe view, operator/platform → full
internal model — via `response_model=None` (no union, no frontend hiding). The owning
customer is now allowed a safe 200 where 9.0.A-1 returned 403; cross-tenant stays 404;
platform reads stay audited; operator/platform responses and lifecycle are unchanged.

**Existing customer-response leaks closed:** `POST /bookings`, `POST /bookings/{id}/cancel`,
and `POST /trip-requests/{id}/offers/{offer_id}/select` previously returned the full
internal object to the acting customer; they now return the customer-safe view (domain
behavior unchanged).

## Payment status vs. initiation

The customer payment view is **status only** (id, booking id, status, currency, total /
authorized / captured amounts, *aggregate* refunded amount, timestamps). Customers get no
allocation, no refund list (`/payments/{id}/allocation`, `/refunds` stay platform-read-only,
ADR-043), and no payment operational command — create/authorize/capture/void/refund remain
denied to customers. This is visibility only; there is no payment initiation, checkout,
card collection, or live provider integration.

## Route-policy

80 → **83** normalized entries (76 → **79** OpenAPI ops + 4 docs) — the three `/me`
routes are `PHASE_9_0B_BOUND`. Existing routes that gained a customer-safe projection keep
their authorization-phase disposition; their notes record the 9.0.B projection. No pending
disposition remains; PUBLIC 15 / ALREADY_BOUND 19 / P1 16 / P2 24 / P3 6 / P0B 3.

## Tests

Self-provisioning (one tenant, neutral identity, safe audit, repeated/concurrent → one
tenant, invitation & existing-membership precedence, suspended user skipped); `/me` list
isolation (A/B both directions), empty, ordering, bounded pagination, no-customer-context
403; offer/booking/payment projections (owning customer safe 200, operator/platform full,
cross-customer 404); negative contract (forbidden fields structurally absent, incl. lists);
payment status safe + allocation/refund/ops still denied; full regression preserved.

## Migration

**None.** Uses existing Phase 8 entities and canonical joins; no denormalized ownership
columns on `Booking`/`Payment`. `alembic check` reports no drift.

## Phase 9.1 boundary (deferred)

Customer Portal UI, login/register/organization-selector UI, Next.js client and proxy,
CORS, customer profile editing (including replacing the provisional account name),
passenger/trip editing, and any payment initiation / live provider work.
