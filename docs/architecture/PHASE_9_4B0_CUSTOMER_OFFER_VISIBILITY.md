# Phase 9.4.B0 — Customer-safe offer publication boundary

## Scope and canonical base

This backend-only prerequisite is based on canonical `origin/main` commit
`7c58cf346b303b0acfb47aaf386f1a9473851587` (the merge commit for PR #31). It does
not add Phase 9.4 customer UI; `apps/web` remains byte-identical to the base. The B1
timing gate remains a separate concern.

## Publication defect

`GET /api/v1/trip-requests/{trip_id}/offers` authorized access to the customer-owned
trip correctly, but then loaded every persisted offer through the same unfiltered read
used by the platform audience. The customer-safe response schema prevented confidential
field disclosure, but it did not prevent unpublished `DRAFT` or fail-closed `WITHDRAWN`
offers from appearing. Frontend filtering cannot establish a publication boundary: the
unpublished record would already have crossed the server trust boundary and any other
client could consume it.

## Server-side policy

Persisted lifecycle status is the sole publication authority for the customer audience:

| Persisted status | Customer result |
| --- | --- |
| `DRAFT` | Hidden |
| `SUBMITTED`, unexpired | Visible as `SUBMITTED` |
| `SUBMITTED`, expired by `valid_until` | Visible as effective `EXPIRED` |
| `SELECTED` | Visible as `SELECTED` |
| `WITHDRAWN` | Hidden |

`EXPIRED` remains derived during response projection and is not persisted.

The offers repository now exposes a dedicated customer-visible query constrained to
persisted `SUBMITTED` and `SELECTED` states. The offer service preserves the trip
existence boundary and provides a matching customer-visible read. After ownership and
permission enforcement, the router selects that read only for the server-determined
customer audience. The existing unfiltered repository/service read remains unchanged for
the authorized internal/platform audience, preserving visibility of `DRAFT`, `SUBMITTED`,
`WITHDRAWN`, and `SELECTED` records and the existing deterministic ordering.

## Preserved contracts

- Ownership resolution, active organization handling, permissions, and cross-customer
  concealed `404` behavior are unchanged.
- The dedicated customer-safe response schema is unchanged and still excludes operator
  and aircraft IDs, operator amount, platform fee, operator notes, compliance/provider
  data, and administrative metadata.
- Offer selection semantics are unchanged: eligibility, concurrency, the selected offer's
  transition to `SELECTED`, the trip remaining `SUBMITTED`, and the absence of automatic
  booking/payment creation all remain governed by the existing service and ADR-015.
- No API route, response schema, route-policy entry, database model, index, enum, or
  migration was added or changed. Alembic head remains `20260813_0009` with no `0010`.
- IAM, authentication/session, operator permissions, Stripe/payments, bookings, email,
  provider configuration, dependencies, CI, Docker, and Vercel configuration are outside
  this change.

## Verification

A PostgreSQL-backed mixed-lifecycle test creates one customer trip containing `DRAFT`,
future `SUBMITTED`, expired persisted `SUBMITTED`, `WITHDRAWN`, and `SELECTED` offers. It
asserts exact IDs and effective statuses for the customer publication set, proves the
platform audience still receives the complete lifecycle set, locks the confidential-field
boundary, and re-proves cross-customer concealed `404` isolation. Existing full-suite
selection, concurrency, schema, OpenAPI, route inventory, and authorization regressions
remain authoritative.

This server-side publication boundary enables Phase 9.4.A to expose customer offer reads
without relying on Web filtering.
