# ADR-017: Booking lifecycle, operator confirmation, rejection, and cancellation

## Status

Accepted

## Context

Sky Bridge Jet may only represent a flight as booked once the responsible
operator confirms the reservation. The booking workflow must clearly distinguish
requested, confirmed, rejected, and cancelled, with explicit legal transitions
and deterministic failure for illegal ones. Rejection and cancellation must
remain auditable, and Phase 4 must not implement payment or financial
settlement.

## Decision

The `Booking` lifecycle has four persisted states and these legal transitions:

```
PENDING_OPERATOR_CONFIRMATION -> CONFIRMED
PENDING_OPERATOR_CONFIRMATION -> REJECTED
PENDING_OPERATOR_CONFIRMATION -> CANCELLED
CONFIRMED                     -> CANCELLED
```

`REJECTED` and `CANCELLED` are terminal. Any other transition (for example
`REJECTED -> CONFIRMED`, `CANCELLED -> CONFIRMED`, `CONFIRMED -> PENDING`) fails
deterministically with a safe 409.

**Confirmation** and **rejection** are operator actions: the command carries the
acting operator id, which must match the booking's operator, and requires the
booking to be pending. Confirmation records `confirmed_at` and an optional
operator confirmation reference and note. Rejection records `rejected_at`, a
required structured `RejectionReason`, and an optional note; it never deletes the
booking.

**Cancellation** records `cancelled_at`, the initiating `CancellationActor`
(customer, operator, or platform), an optional structured reason, and an optional
note. It is workflow state only — no penalties, refunds, credits, or settlement
are computed. Confirmation is deliberately **not** conditional on any payment
flow; the ordering between customer payment authorization, operator
confirmation, and booking confirmation is a later-phase decision and is not
invented here.

## Consequences

The workflow truthfully distinguishes "operator confirmed" from "operator
rejected/cancelled". Illegal transitions cannot silently corrupt state. All
historical outcomes remain queryable. Operator actions are architecturally
distinct from customer/platform cancellation, so future authorization can be
layered without redesign.
