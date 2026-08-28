# Phase 9.8.B — Payment Exception and Reconciliation Operations

Phase 9.8.B adds a bounded internal finance workspace without creating a second payment
state machine. The canonical `Payment` aggregate and `PaymentOperation` durable-attempt ledger
remain authoritative. No migration, worker, dependency, live Stripe call, capture/void/refund
UI, settlement claim, or automatic retry is introduced.

## Server boundary

- `GET /api/v1/platform/payments/exceptions` requires `payment.read` granted by a validated
  `PLATFORM` membership, accepts `limit` 1–100,
  non-negative `offset`, optional operation/result filters, and orders by operation
  `updated_at DESC, id DESC`. Its default is PENDING, UNKNOWN, and FAILED.
- `GET /api/v1/platform/payments/{payment_id}` requires the same platform-scoped `payment.read`
  and returns an exact
  safe Payment projection plus a bounded operation timeline (maximum 100).
- `POST /api/v1/platform/payment-operations/{operation_id}/reconcile` has no request body and
  requires `payment.operate`. The server resolves the operation and Payment. Amount, currency,
  provider, operation type, Payment ID, idempotency key, correlation identity, customer, and
  operator are never browser authority.

Global `payment.read` alone is deliberately insufficient because customer and operator roles use
that permission for their own bounded payment views. The API gate is the security authority and
denies direct customer/operator calls before queue or Payment lookup; the Web platform-membership
layout remains a consistent UX boundary, not the authorization control.

The read projections omit customer/passenger PII, card data, client secrets, webhook secrets,
idempotency keys, and credentials. Opaque provider references and correlation IDs are factual
operations identifiers, not credentials.

## Reconciliation decision

Only `UNKNOWN` AUTHORIZE, CAPTURE, or VOID operations are manually actionable. `PENDING` is
visible but not retried because it may represent SCA, webhook-in-flight, or another unresolved
provider interaction. FAILED is historical review information. REFUND remains outside this
manual workspace.

The service locks and claims the exact operation as PENDING before dispatch. It then invokes
the existing durable command with the operation's stored idempotency key; the provider receives
the existing correlation UUID. No new operation row or logical identity is minted. A concurrent
reviewer observes PENDING and fails closed. Provider response loss returns the same operation to
UNKNOWN. There is no automatic retry. Verified webhooks continue to use the canonical
cross-Payment and event/operation compatibility checks and converge idempotently.

No background worker is necessary for this bounded manual control plane. Automated scheduled
reconciliation is deferred; webhook reconciliation remains authoritative.

## Browser boundary

The proxy exposes exactly the exception collection, UUID Payment detail, and UUID operation
reconcile route. Reads are same-origin, `no-store`, abortable requests. The bodyless write uses
the existing same-origin CSRF transport. Finance reviewers can read; only principals with
`payment.operate` see reconciliation controls.

Queue requests use abort plus request epochs and fetch one bounded page. Detail and mutation
state are keyed by Payment ID and monotonic generation. Confirmation names the operation,
operation result/type, Payment state, attempt count, and explicitly states that existing durable
identity is reused. Duplicate clicks are synchronously guarded. A 409 causes at most one
authoritative refresh and no retry. An unconfirmed network result is presented factually and
requires explicit refresh.

`CAPTURED` is described only as a payment state and never as settlement, operator payment, or
money transfer.

## Verification contract

Tests cover bounded/read-only discovery, safe schemas, role separation, exact proxy exposure,
same-operation identity, duplicate rejection, lost AUTHORIZE/CAPTURE/VOID recovery, canonical
webhook and cross-Payment protections, page/filter races, explicit confirmation, read-only UI,
409 recovery, and unknown-result copy. Route inventory becomes 110 registered / 106 OpenAPI / 4
infrastructure routes. Alembic remains the single `20260827_0010` head with no `0011`.
