# ADR-020: Payment aggregate and operations ledger

## Status

Accepted

## Context

Phase 5 needs to represent a booking's financial obligation and its authorize /
capture / void / refund history without moving real money, and a card
authorization that fails must not create a second competing obligation.

## Decision

Model one `Payment` aggregate per booking (database `UNIQUE(booking_id)`), plus a
`payment_operations` child table that records every financial command
(`AUTHORIZE`, `CAPTURE`, `VOID`, `REFUND`) with its result, amount, provider
reference, and a unique idempotency key. The payment holds the running totals
(`authorized_amount_minor`, `captured_amount_minor`, `refunded_amount_minor`) and
the lifecycle status; the operations table is both the idempotency ledger and the
attempt/audit trail, and refund operations are the refund history.

## Consequences

A booking can never accumulate multiple independent financial obligations. The
single ledger avoids a proliferation of tables while still capturing retries and
provider attempts. Refund state (partial vs full) is derived from the payment
totals rather than duplicated. No card or bank credentials are stored — only
provider-neutral references.
