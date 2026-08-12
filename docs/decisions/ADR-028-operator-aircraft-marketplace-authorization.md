# ADR-028: Operator/aircraft marketplace authorization

## Status

Accepted

## Context

The existing `Operator → Aircraft` relationship is not sufficient to permit
commercial offers of that aircraft. Operator admission does not automatically
approve every aircraft, and aircraft ownership is not required — an operator may
offer owned, leased, managed, or otherwise operated aircraft.

## Decision

Introduce `operator_aircraft_authorizations` (unique per operator/aircraft pair)
with an `authority_basis` (`OWNED`, `LEASED`, `MANAGED`,
`OPERATED_UNDER_AGREEMENT`, `OTHER`) and its own explicit review lifecycle
(`DRAFT → SUBMITTED → {UNDER_REVIEW} → APPROVED | REJECTED`, `APPROVED →
SUSPENDED`, `SUSPENDED → APPROVED`). A composite foreign key
`(aircraft_id, operator_id) → aircraft(id, operator_id)` enforces at the database
level that the authorized aircraft belongs to the operator. Approval is explicit
and never inherited from operator admission, and it does not imply ownership.

## Consequences

The question "has Sky Bridge Jet reviewed sufficient evidence to admit this
operator/aircraft combination?" has a first-class, auditable answer independent of
operator-level admission. Suspending a combination blocks its future commercial
use while preserving history.
