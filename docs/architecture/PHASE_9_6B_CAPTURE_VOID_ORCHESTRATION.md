# Phase 9.6.B — Trusted capture and void orchestration

Canonical base: `bbcf3c839c2e11ef1e9c1c3880196ebb075ad55b`.

## Policy and authority

An authoritative Booking transition is the only trigger. `CONFIRMED` captures an
`AUTHORIZED` Payment; `REJECTED` and `CANCELLED` void eligible pre-capture states.
A captured Payment is never automatically refunded. The existing Booking request
contracts remain unchanged: callers cannot supply a Payment ID, amount, currency,
provider, or financial command. Payment lookup is server-derived through the
one-Payment-per-Booking relationship. No customer or operator Payment authority is
added.

## Transaction, locking, and idempotency

BookingService locks the Booking first, validates the lifecycle and (for confirm)
revalidates operator and aircraft compliance. It then mutates and flushes the
Booking, locks its Payment, and delegates to PaymentService's existing capture or
void primitive in the same database transaction. This fixed lock order serializes
competing Booking decisions and their financial consequence.

Trusted keys are deterministic and contain no PII:
`booking:{booking_id}:confirm:capture`, `booking:{booking_id}:reject:void`, and
`booking:{booking_id}:cancel:void`. PaymentService retains its PostgreSQL advisory
key lock, unique ledger key, Payment row lock, provider abstraction, lifecycle
validation, and append-only PaymentOperation record. A replay cannot create a
second provider operation.

## State policy

- Confirm: no Payment, `CREATED`, and `AUTHORIZATION_FAILED` are left unchanged;
  `AUTHORIZED` or `CAPTURE_FAILED` uses capture; `CAPTURED` is an idempotent no-op;
  cancelled/refunded states are not captured.
- Reject/cancel: no Payment is a no-op; `CREATED`, `AUTHORIZATION_FAILED`,
  `AUTHORIZED`, and `CAPTURE_FAILED` use canonical void semantics; `CANCELLED` is
  a no-op; captured or refunded states are left unchanged and require a future
  explicit refund policy.
- Compliance failure happens before any Payment lookup or provider call.

## Failure and provider boundary

Acceptance uses only the deterministic FAKE provider and makes no network payment.
A reported capture failure commits `CAPTURE_FAILED` plus a failed CAPTURE ledger
entry while retaining the provider authorization reference. Canonical void contacts
the provider whenever a voidable Payment retains that reference, including
`CAPTURE_FAILED`; only provider success permits local `CANCELLED` and
`VOID/SUCCEEDED`. A reported void failure leaves the Payment in its prior factual
state, retains the reference, and records `VOID/FAILED`; it never fabricates
`CANCELLED`. Provider exceptions roll back the enclosing Booking transaction.

This phase does not claim atomicity across a future external PSP and the database.
Durable unknown-outcome reconciliation/recovery is explicitly deferred to Phase
9.6.C. No automatic refund or automatic financial retry is introduced.

## Compatibility and scope

Customer authoritative reads naturally expose `AUTHORIZED`, `CAPTURED`, or
`CANCELLED` after manual refresh. Operator UX remains Confirm/Reject only. There is
no new route, Web production change, migration, dependency, secret, Stripe UI,
capture/void button, refund behavior, payout, transfer, or settlement claim.

Route inventory remains 87 total / 83 API / 4 non-API. Alembic remains
`20260813_0009`; there is no `0010`.
