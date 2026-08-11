# ADR-022: Financial idempotency and concurrency

## Status

Accepted

## Context

Financial commands may be retried by clients and, in a future integration, by
provider callbacks. No retry or concurrent request may cause a double
authorization, double capture, double or over refund, or a duplicate payment.

## Decision

Every state-changing financial command (`authorize`, `capture`, `void`, `refund`)
carries a bounded, opaque, client-supplied **idempotency key**, stored uniquely in
`payment_operations`. A command first loads the payment with a `FOR UPDATE` row
lock so commands serialize per payment, then: if the key already exists for the
same operation it **replays** the recorded result; if the key was used for a
different operation it fails with a deterministic `idempotency_conflict`; a
concurrent duplicate is caught by the unique constraint. Payment creation is
idempotent per booking (unique `booking_id`): a repeat returns the existing
payment. Idempotency keys are never logged.

## Consequences

Retries and concurrency are safe by construction using database invariants and
row locking, with no distributed idempotency-key platform. This is consistent
with ADR-012's mandate that financial workflows keep explicit aggregate
transaction boundaries.
