# ADR-023: Operator/platform allocation and commercial-snapshot binding

## Status

Accepted

## Context

Sky Bridge Jet is a disclosed intermediary (working assumption). The customer
total is economically split into the operator amount, the Sky Bridge Jet platform
fee, and the tax component from the Phase 3/4 commercial snapshot. The platform
must never treat the entire customer payment as its own revenue, and the payment's
commercial basis must not diverge from the booking's.

## Decision

The `Payment` snapshots the booking's `currency`, `operator_amount_minor`,
`platform_fee_minor`, `tax_amount_minor`, and `total_amount_minor` (integer minor
units, ADR-013), and this snapshot is bound to the booking by a **six-column
composite foreign key** into a `bookings` composite unique key, so the split can
never diverge. `total = operator + fee + tax` and non-negativity are enforced by
`CHECK` constraints on both tables. The allocation is exposed explicitly, keeping
operator amount, platform fee, and tax economically distinct.

## Consequences

The operator/platform/tax split is a first-class, database-guaranteed fact.
Settlement references the operator's economic allocation, never the total.
Refund-to-allocation apportionment and payout timing are deliberately left to a
later, separately approved policy (see ADR-024 and the settlement section of the
Phase 5 architecture document).
