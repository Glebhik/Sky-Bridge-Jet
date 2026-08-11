# ADR-015: Offer lifecycle, quote immutability, and single-selection concurrency

## Status

Accepted

## Context

Operators submit offers that customers compare and select. Historical quote
integrity matters: once an offer is on the marketplace its commercial terms must
not silently change. Expiration must be deterministic without a background
scheduler. A customer may select at most one offer per trip request, and that
invariant must hold under concurrent requests, enforced by the database rather
than application code alone.

## Decision

**Lifecycle.** An offer has persisted states `DRAFT`, `SUBMITTED`, `WITHDRAWN`,
and `SELECTED`, with explicit transitions: `DRAFT -> {SUBMITTED, WITHDRAWN}` and
`SUBMITTED -> {WITHDRAWN, SELECTED}`. `WITHDRAWN` and `SELECTED` are terminal.

**Immutability.** Only `DRAFT` offers can be edited. Submission freezes the
commercial terms; a change requires withdrawing and creating a replacement
offer. Operator and aircraft identity are snapshotted onto the offer at creation
so it stays historically meaningful if that reference data changes later.

**Expiration.** Every submitted offer carries a timezone-aware UTC `valid_until`,
required to be in the future at submission. `EXPIRED` is an effective status
derived by comparing `valid_until` to the current time on read and command
paths; it is never persisted, so no scheduler is needed. An effectively expired
offer cannot be selected.

**Single selection.** Selection acquires a `SELECT ... FOR UPDATE` row lock on
the trip request so concurrent selections serialize, then verifies no offer is
already selected. A PostgreSQL partial unique index,
`operator_offers(trip_request_id) WHERE status = 'SELECTED'`, is the ultimate
backstop that makes two selected offers per trip physically impossible. A second
partial unique index prevents duplicate active offers for the same
trip/operator/aircraft.

The Phase 2 `TripRequest` lifecycle is intentionally left unchanged: selection is
recorded on the offer, not by mutating the trip aggregate.

## Consequences

Quotes are tamper-evident and comparable over time. Expiration needs no
infrastructure. The single-selection invariant is guaranteed by the database, in
line with ADR-012's mandate that quote and booking workflows keep explicit
aggregate transaction boundaries. Selection expresses commercial intent only and
creates no booking, payment, contract, or reservation.
