# ADR-018: Booking concurrency and idempotency

## Status

Accepted

## Context

Booking creation and state changes are operationally important and may later be
driven through unreliable networks and provider adapters. A trip request must
never accidentally produce multiple active booking workflows, and concurrent or
repeated commands must not corrupt state. Application-level checks alone are
insufficient.

## Decision

**One active booking per trip.** A PostgreSQL partial unique index on
`bookings(trip_request_id) WHERE status IN ('PENDING_OPERATOR_CONFIRMATION',
'CONFIRMED')` makes two simultaneously active bookings for one trip impossible.
Rejected and cancelled bookings fall outside the predicate, so they remain as
history while a new workflow is permitted.

**Creation concurrency.** Creation locks the trip request row with `SELECT ...
FOR UPDATE` so concurrent creations serialize, then checks for an existing active
booking; the partial unique index is the ultimate backstop. Two simultaneous
creations therefore yield exactly one booking.

**Command concurrency.** Confirmation, rejection, and cancellation load the
booking with a row lock (`SELECT ... FOR UPDATE`) and re-validate the transition,
so a confirm/reject or confirm/cancel race resolves to one valid terminal state
rather than a contradiction.

**Idempotency policy.** Repeated creation for an already-active trip returns a
deterministic 409 conflict rather than a duplicate. Repeated confirmation,
rejection, or cancellation of a booking already in a terminal (or non-pending)
state returns a deterministic 409 `invalid_booking_state`. Database invariants
and deterministic command semantics are used in preference to a distributed
idempotency-key platform, which is out of scope.

## Consequences

Correctness holds under concurrency and retries without process-local locks or
external coordination, consistent with ADR-012. Clients retrying a create should
read the trip's booking rather than expecting silent idempotent creation.
