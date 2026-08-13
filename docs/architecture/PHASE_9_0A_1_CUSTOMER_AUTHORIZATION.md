# Phase 9.0.A-1 — Customer-Chain Resource Authorization

## Purpose

The first Phase 9 delivery unit is a **security gate**, not Customer Portal UI. It
closes the Phase 8 authorization debt for the **customer chain**: every customer-chain
route now enforces per-resource authorization server-side, so **Customer A can never
read or act on Customer B's resources**, and body-supplied owner identifiers can never
transfer ownership. No Customer Portal feature may proceed until this gate (and its
operator/payment siblings) is merged and verified.

This unit is deliberately bounded. It does **not** implement the operator chain
(9.0.A-2), payment operations or `payment.operate` (9.0.A-3), customer
self-provisioning or customer-safe read models (9.0.B), any Customer Portal UI, a
Next.js proxy, CORS changes, or any database migration.

## Enforcement architecture (ADR-040)

```
request → global auth gate (Phase 8) → route handler
                                          │
                                          ├─ active CUSTOMER org resolved from principal (validated)
                                          ├─ ownership resolved by join (immutable → race-free)
                                          └─ authorize(principal, permission, ResourceScope.customer(owner))
                                                 allow · 403 (visible, no permission) · 404 (concealed)
```

- **One seam** (`modules/access.py`) reuses the Phase 8 `Principal` / `ResourceScope`
  / `is_authorized`. No competing framework.
- **Active CUSTOMER organization**: auto-selected when the principal has exactly one;
  otherwise a membership-validated `X-Organization-Id` is required. OPERATOR/PLATFORM
  orgs can never be a customer context; client-supplied ids are never trusted.
- **Ownership** is resolved authoritatively by join and is immutable, so
  resolve-then-act needs no lock for ownership (lifecycle still uses the services'
  existing row locks / optimistic version).
- **Owner ids are principal-derived**: on create, the customer comes from the active
  org; a body `customer_id` may only confirm that tenant (mismatch → 404). A platform
  principal with `customer.write` may act for an explicit existing customer — the one
  audited platform exception.

### 401 / 403 / 404 / 409 (deny by default, ADR-040)

| Code | When |
| --- | --- |
| 401 | not authenticated / session invalid or expired |
| 403 | authenticated, tenant visible, but missing the action permission |
| 404 | absent, or another tenant whose existence is concealed |
| 409 | visible resource, invalid lifecycle/concurrency transition |

## Customer-chain routes secured in this PR

| Route | Method | Rule |
| --- | --- | --- |
| `/customers` | POST | platform-admin only (`admin.organizations.manage`) until 9.0.B self-provisioning |
| `/customers/{id}` | GET | `customer.read`, owner==id, cross-tenant 404 |
| `/passengers` | POST | `customer.write`, customer derived from active org, body id validated |
| `/passengers/{id}` | GET | `customer.read`, via `passenger.customer_id` |
| `/trip-requests` | POST | `trip.write`, customer derived; body id validated |
| `/trip-requests/{id}` | GET | `trip.read`, via `trip.customer_id` |
| `/trip-requests/{id}/submit`,`/cancel` | POST | `trip.write` + owner + lifecycle |
| `/trip-requests/{id}/offers` | GET | ownership enforced; confidential → platform-only (ADR-041) |
| `/trip-requests/{id}/offers/{offer_id}/select` | POST | `trip.write` + owner; service checks offer↔trip + status |
| `/bookings` | POST | owner via selected offer→trip; body ids not trusted |
| `/bookings/{id}`, `/trip-requests/{id}/booking` | GET | ownership; confidential → platform-only |
| `/bookings/{id}/cancel` | POST | customer side (owner); operator side → 9.0.A-2 |
| `/payments/{id}`, `/bookings/{id}/payment` | GET | ownership; confidential → platform-only |

## Platform-exception security auditing (H1, ADR-040)

A **platform exception** is a successful access to a customer-owned resource by a
PLATFORM principal that is not a member of the owning customer organization (a
cross-tenant/arbitrary-tenant action authorized by a platform role, not by customer
ownership). Every such success is recorded **once, append-only** in the Phase 8
`auth_audit_log` (`AuditRepository`) under the stable event
`platform_authorization_exception`.

- **Which actions trigger it**: platform-controlled Customer creation
  (`POST /customers`); platform reads of a Customer/Passenger/TripRequest outside a
  customer membership; platform creation of a Passenger/TripRequest for a Customer;
  platform trip submit/cancel, offer select, booking create/cancel; and platform
  access to the confidential Offer/Booking/Payment reads.
- **Who does not trigger it**: an ordinary customer acting within its own tenant
  emits nothing; a denied customer/operator attempt is never recorded as a success.
- **Safe metadata only**: acting user, acting platform organization, normalized
  action/route id, permission, resource type, an opaque resource identifier,
  correlation id, and `result=allowed`. Never passwords, tokens, financial splits,
  PII, or request bodies.
- **Durability / transaction semantics**: a privileged **read** commits its audit
  record before the response is serialized; a privileged **write** passes an
  `on_commit` hook that the service runs **inside its own transaction**, so the audit
  commits atomically with the mutation and rolls back with it. A failed mutation
  therefore leaves no misleading successful-action record, and there is no unsafe
  separate post-commit write.

## Ownership immutability (L1)

The resolve-then-mutate pattern is race-free because customer ownership is immutable:
no route changes `trip.customer_id` / `passenger.customer_id`, and there is no
ownership-transfer endpoint. A future ownership-transfer endpoint must move ownership
resolution, authorization, and the mutation into one locked, atomic transaction
(ADR-040). This PR adds no such endpoint and no migration for it.

## Confidential-field boundary (ADR-041)

`OperatorOfferResponse` / `BookingResponse` / `PaymentResponse` still expose
`operator_amount_minor` and `platform_fee_minor`. Until the Phase 9.0.B customer-safe
projections exist, those five reads serve the full response **only to a platform
viewer**; an owning customer gets a temporary 403; cross-tenant gets 404. No customer
ever receives a body with the confidential fields (proven by negative tests).

## Route-policy registry & coverage invariant (ADR-040)

`modules/route_policy.py` classifies **every** registered route/method with an
explicit disposition. `tests/test_route_policy_coverage.py` introspects the live app
and fails if any route is unclassified, omitted, duplicated, or a protected route is
marked public. Canonical set: **76 OpenAPI operations + 4 documentation routes = 80**
(HEAD/OPTIONS excluded; documentation routes are app-level, outside the versioned
gate). Pending dispositions (9.0.A-2 / 9.0.A-3) never weaken the global authentication
gate.

## Tests

- **Coverage**: 80-route classification; unclassified/duplicate/misclassified-public
  all fail.
- **Cross-customer isolation (both directions)**: every bound route is covered with a
  scoped-customer negative test — customer/passenger/trip reads, trip submit **and
  cancel**, **offer select** (on another tenant's trip and a foreign offer against
  one's own trip), **booking create**, **booking cancel**, **trip→booking read**, and
  **booking→payment read** all return 404 with DB state proven unchanged; A→B and a
  mirrored B→A (`test_symmetric_b_cannot_access_a`).
- **Body-owner protection**: supplying another tenant's `customer_id` never transfers
  ownership (404).
- **Active organization**: single auto-resolves; multiple require a validated
  `X-Organization-Id`; foreign org and operator-org contexts rejected.
- **Confidential reads**: customer 403, platform 200, cross-tenant 404; customer body
  never contains confidential fields.
- **Platform-exception audit (real PostgreSQL)**: a successful platform exception
  writes exactly one record with the correct actor and safe metadata; repeated
  requests append separate records (never mutate); an ordinary customer in its own
  tenant and a denied cross-tenant attempt write nothing; an operator cannot reach the
  branch; a failed mutation writes no record, and a failing audit hook rolls the
  mutation back (atomicity, both directions).
- **Concurrency (real PostgreSQL)**: concurrent submits transition once (200 + 409);
  a cross-tenant actor cannot race a lifecycle change (intruder 404, owner 200).
- **Fixture integrity**: the new authorization tests use **real tenant-scoped CUSTOMER
  principals** (distinct users/orgs/memberships for A and B), never PRODUCT_OWNER. The
  legacy Phase 2–8 *business* suites legitimately authenticate as the audited
  PRODUCT_OWNER platform actor — they predate tenancy and exercise business logic, not
  authorization; the dedicated cross-tenant suite is what proves the gate, so the
  shared fixture masks no authorization path. Anonymous and insufficient-permission
  negative tests are preserved.

## Migration

**None.** Ownership resolves through existing relationships; no schema change.

## Pending boundaries

- **9.0.A-2** — operator-chain authorization (operators, aircraft, offers manage,
  booking confirm/reject/operator-cancel, compliance operator-self routes).
- **9.0.A-3** — payment operations: the additive `payment.operate` permission
  (`PLATFORM_ADMIN`/`PRODUCT_OWNER` only; `PLATFORM_FINANCE_REVIEWER` stays read-only,
  per PO B1), and allocation/refund-list operator/platform scoping. `payment.refund`
  unchanged.
- **9.0.B** — customer self-provisioning and the customer-safe offer/booking/payment
  projections that flip the temporary 403s to safe 200s.
