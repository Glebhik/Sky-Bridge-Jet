# Phase 9.1.A — Pre-Portal Contract and Account-Recovery Hardening

## Purpose

Phase 9.1.A is the **backend hardening** that must land before any Customer Portal UI. It
closes the two preliminary-debt items from the PR #15 (Phase 9.0.B) audit: (A) typed,
validated, accurately documented **audience-aware response contracts** for the eight shared
resource routes; and (B) a safe, authenticated **customer-account recovery** endpoint for
stranded users. It is strictly migration-free and adds no frontend, proxy, CORS, live
provider, role, or permission. The web foundation (proxy, typed client, auth/session state,
protected shell, production docs posture) is deferred to Phase 9.1.B.

## A — Typed audience-aware contracts (ADR-046)

The eight shared routes previously used `response_model=None` (Phase 9.0.B), leaving an
empty OpenAPI 2xx body and no response validation. They now declare a **discriminated
customer/internal union** tagged by a required `response_audience` literal:

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

`modules/audience.py` defines shared-route-specific wrappers: `Customer*Response` subclass
the Phase 9.0.B customer-safe views, `Internal*Response` subclass the internal schemas, each
adding the discriminator. Because they subclass, the base `/me` list items and the
operator/platform-only routes are **untouched**. The offers route keeps its **top-level
array** (`list[…]` of the discriminated item union).

**Confidentiality boundary.** The customer variants are structurally safe — they never carry
`operator_amount_minor`, `platform_fee_minor`, allocation, settlement eligibility, provider
references, provider status, raw `PaymentOperation`, idempotency keys, platform notes, or
audit metadata, even nested. The handler authorizes first, selects the audience with
`access.is_customer_view`, and builds the matching envelope from the vetted view. FastAPI
validates the returned instance against the discriminated union; selection is by the literal
discriminator, so there is no coercion or field stripping, and a payload lacking the
discriminator fails closed. Cross-tenant remains 404, insufficient action 403, invalid
lifecycle 409; platform-exception auditing and payment-operational restrictions are
unchanged.

**Response-validation guarantee.** `response_model` is now set on all eight routes (never
`None`), so runtime response-model validation is active. Tests inspect the *generated*
OpenAPI (non-empty discriminated 2xx, both variants as components, `CustomerOfferResponse`
present, no confidential field in any customer variant, stable operation ids, documented
error envelopes) and assert the *runtime* audience tag on real requests (customer →
`"customer"` + no confidential field; operator/platform → `"internal"` + the split).

## B — Customer-account recovery (ADR-047)

`POST /api/v1/auth/customer-account/recover` provisions a personal customer tenant for a
stranded authenticated user (ACTIVE + verified, no membership, no valid pending invitation).
It is a non-public POST, so the global gate enforces **authentication + CSRF**; it is
**rate-limited** (5/60s per user). The body is empty; identity is the session principal.

- **Eligibility / denial:** existing membership → 409 `account_already_provisioned`; valid
  pending invitation → 409 `pending_invitation_exists`; not ACTIVE → 401 at the gate (403 at
  the service, defense in depth); rate limit → 429. Expired/revoked invitations do **not**
  block. Error bodies never disclose a foreign organization, issuer, or role.
- **Invitation precedence:** a valid pending invitation suppresses verification-time
  provisioning *and* blocks recovery; expired and revoked invitations do neither.
- **Concurrency & transaction model:** one transaction, canonical **user row locked first**,
  so concurrent/repeated recovery yields at most one tenant (the loser gets 409). Recovery
  vs. invitation acceptance cannot produce conflicting or partial state (recovery is gated on
  "no valid pending invitation" under the lock; acceptance commits membership + invitation
  status atomically). A provisioning or audit failure rolls back the whole tenant.
- **Reuse:** recovery calls the single `provision_personal_customer` path (ADR-044); that
  function gained only an `event` parameter.
- **Audit:** exactly one append-only `customer_account_recovered` on success (acting user id
  + new org id only); `customer_self_provisioned` is unchanged. Denied/failed/rate-limited
  requests write no success event.

## Route-policy

83 → **84** normalized entries (79 → **80** OpenAPI operations + 4 documentation routes).
The one new route — the recovery endpoint — is `PHASE_9_1A_BOUND`; the typed-contract work
adds no route. A coverage test asserts 84/80/4, that the recovery route is bound and never
public, and that no pending/unclassified/orphan/duplicate entry remains.

## Migration

**None.** The typed contracts are schema-only. Recovery reuses existing Phase 8 entities and
canonical joins — no new table, no denormalized ownership column. `alembic check` reports no
drift and no new migration file exists.

## Phase 9.1.A → 9.1.B boundary

Phase 9.1.A is backend only. Deferred to Phase 9.1.B: the same-origin Next.js→API proxy, the
typed API client generated from this now-accurate OpenAPI, frontend auth/session state, the
active-organization selector, the protected application shell, and disabling `/docs`,
`/redoc`, and `/openapi.json` in production. No Customer Portal feature screens
(passenger/trip/offer-comparison/booking/payment), profile editing, live payment provider,
or checkout are part of either 9.1.A or the 9.1.B foundation slice.
