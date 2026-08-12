# ADR-026: Operator marketplace admission lifecycle

## Status

Accepted — marketplace admission only; specialist review required before production

## Context

Until Phase 6 an operator was treated as commercially legitimate simply because
its record existed. Sky Bridge Jet must instead decide, through structured review,
whether an operator may participate commercially in its marketplace — without
representing itself as an aviation regulator.

## Decision

Introduce a separate `operator_admissions` record (one per operator, database
unique) with an explicit lifecycle: `DRAFT → SUBMITTED → {UNDER_REVIEW} →
APPROVED | REJECTED`, `APPROVED → SUSPENDED`, `SUSPENDED → APPROVED`,
`REJECTED → SUBMITTED`. Illegal transitions fail deterministically. Admission is
never inherited or auto-created: existing operators have no admission row and are
therefore not admitted. `APPROVED` means "admitted to the Sky Bridge Jet
marketplace under the current compliance procedure", explicitly **not** a
government certification that the operator is legally authorized to perform every
flight.

## Consequences

Marketplace admission is a first-class, auditable decision distinct from
operational status. No auto-approved-legacy-operator loophole exists. Admission
is necessary but not sufficient for route-level legality (deferred).
