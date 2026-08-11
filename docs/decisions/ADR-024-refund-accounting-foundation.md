# ADR-024: Refund accounting foundation

## Status

Accepted

## Context

Phase 5 needs correct refund accounting without building credit notes, invoices,
VAT adjustments, or an automatic cancellation-refund policy.

## Decision

Refunds are `REFUND` operations recorded in `payment_operations`, each with an
amount, result, provider reference, and unique idempotency key. A refund is
permitted only when the payment is `CAPTURED` or `PARTIALLY_REFUNDED`; the amount
must not exceed the remaining captured amount (`captured - refunded`). Cumulative
refunds are tracked in `refunded_amount_minor` with a database
`CHECK(refunded_amount_minor <= captured_amount_minor)` backstop. A refund uses
the payment's currency (no cross-currency refund). Reaching the full captured
amount moves the payment to `REFUNDED`; a lesser amount to `PARTIALLY_REFUNDED`.
Refund history is preserved. No cancellation-fee, VAT, or refund-policy amount is
ever calculated automatically — a refund amount is always supplied explicitly.

## Consequences

Over-refund is impossible (service check plus database constraint plus row
locking), refunds are idempotent and concurrency-safe, and history is auditable.
How a refund apportions across operator/platform/tax, and whether a cancellation
implies a refund, remain deferred commercial/legal/accounting decisions.
