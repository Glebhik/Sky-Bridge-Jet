# ADR-029: Compliance gating of offers and booking confirmation

## Status

Accepted

## Context

Marketplace admission is worthless unless it actually gates commercial activity,
and compliance can lapse between an offer being created and a booking being
confirmed. The gate must be a single, explainable decision, enforced in the
domain/service layer (never only the frontend), and safe under concurrency.

## Decision

A single `ComplianceEvaluator` is the only place eligibility is decided. It
returns an explainable decision (eligible plus structured
`EligibilityReasonCode`s) from current effective state: operator admission
`APPROVED`, at least one currently-valid (verified and unexpired) operating
authority and operator-level insurance, the aircraft belonging to the operator,
and the operator/aircraft authorization `APPROVED`.

**Offer gate:** `OperatorOfferService.create` calls the evaluator and refuses to
create an offer for an ineligible operator/aircraft (safe 409 with reasons).
**Booking confirmation recheck:** `BookingService.confirm` re-evaluates before
turning a booking `CONFIRMED`; a lapse blocks confirmation (safe 409) and does
**not** mutate or cancel the booking. Both gates evaluate with `SELECT … FOR
UPDATE` locks on the admission and authorization rows, so a concurrent suspension
serializes and can never yield an offer from — or a booking confirmed under —
suspended compliance.

Interaction with payments: because Phase 5 capture already requires a `CONFIRMED`
booking, a compliance lapse that blocks confirmation also prevents capture. No
automatic void or refund is triggered; the safe explicit financial-resolution
boundary from Phase 5 is preserved.

## Consequences

Ineligible operators cannot transact, lapses are caught at the confirmation
boundary, and history is preserved. Eligibility means "meets Sky Bridge Jet's
configured Phase 6 admission prerequisites", not route-level legality.
