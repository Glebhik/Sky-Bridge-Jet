# Phase 9.3.B0 — Customer write-context hardening

## Starting point

- Canonical base (`origin/main`): `bb6e6727008f5eec10ec6c115b35e426612e2c85` (post Phase 9.3.A).
- This is a **security-hardening / API-contract correction**, not a new feature, and the
  prerequisite that unblocks Phase 9.3.B (customer trip-request creation).

## The blocker (discovered during the 9.3.B contract audit)

`POST /api/v1/passengers` (`PassengerCreate`) and `POST /api/v1/trip-requests`
(`TripRequestCreate`) both **required** a `customer_id` in the request body, yet **no
customer-readable surface exposes the caller's own `customer_id`**: `/auth/me`'s
`MembershipView` carries only `organization_id`, the web session model derives only
`{organizationId, role}`, and `/me/*` reads compute `customer_id` server-side without ever
returning it. A first-time customer (no prior trips) therefore had no way to construct a
valid create payload — the create flow was unreachable from the browser.

The browser **should not** need an internal customer UUID at all: the authoritative customer
is already derived server-side by `access.resolve_write_customer()` from the authenticated
principal and the validated active organization (`organization.customer_id`). A body-supplied
`customer_id` is only a confirmation, and a *mismatching* value is concealed as `404`.

## The change (minimal)

- `PassengerCreate.customer_id` and `TripRequestCreate.customer_id` become
  **`UUID | None = None`** — optional confirmation only.
- `TripRequestService.create` / `PassengerService.create_passenger` add a small defensive
  narrowing: the router rewrites `customer_id` to the resolved owner before calling the
  service, so a `None` reaching the service is a missing customer (`_not_found("Customer")`).
  This is type-safety, **not** an ownership-logic change.

**No** handler/ownership change (`access.py`, `iam/**`, the routers are byte-identical),
**no** new endpoint, **no** route-policy change, **no** migration, **no** DB-model change,
**no** `/auth/me` or browser-session change, **no** client code.

## Tenant isolation is preserved

The authoritative ownership chain is unchanged and entirely server-side:

```
authenticated User → validated active Organization → organization.customer_id → Customer
```

Behaviour of `resolve_write_customer` for a customer principal (unchanged):

- **omitted** `customer_id` → the server derives it from the active org;
- **correct** `customer_id` → accepted as confirmation;
- **mismatching** `customer_id` → rejected/concealed as `404` (never confirms another tenant);
- a **forged / non-member** `X-Organization-Id` → rejected (`403`) even when `customer_id`
  is omitted — omission does not bypass active-organization validation.

## Tests (DB-backed)

Added to `tests/access/test_customer_chain_authorization.py`:

- passenger create with **omitted** `customer_id` → `201`, owned by the authoritative customer;
- trip-request create + submit with **omitted** `customer_id` → `DRAFT` → `SUBMITTED`, owned
  by the authoritative customer;
- omitted `customer_id` with a **forged** `X-Organization-Id` → `403`.

Existing isolation tests remain green (correct-id accepted; wrong-id concealed `404`;
cross-customer `404`; ambiguous multi-membership requires an explicit org). API suite:
**500 passed** (497 + 3). Route inventory **85 / 81 / 4**, Alembic head **20260813_0009**,
no `0010`.

## Enables

Phase 9.3.B (first-time customer passenger + trip-request creation) can now be implemented as
a pure web-only slice: the browser sends session + validated `X-Organization-Id` and omits
`customer_id` entirely; the server derives ownership.

## Not in scope / deferred

No cancel (9.3.C), no dashboard aggregation (9.3.C), no offers/booking/payment, no Grok
(deferred until after 9.3.C), no `/auth/me` `customer_id` exposure. The B1 production email
timing gate remains a separate production-hardening item.
