# Phase 9.8.D0 — Operational Handoff Foundation

## Decision

The original Phase 9.8.D implementation was blocked because the canonical model ended
at Booking and there was no durable operational aggregate, ownership boundary, or
factual lifecycle authority on which a safe post-booking UI could rely. D0 resolves
only that backend prerequisite.

Phase 9.8.D0 introduces `FlightOperation` as the minimal durable post-booking
aggregate. One operation represents the operational handoff of exactly one confirmed
`Booking`. It is not a second booking, flight schedule, passenger manifest, payment
record, or mutable dispatch workflow.

The aggregate has one factual state, `HANDOFF_CREATED`. That fact is authored when a
booking successfully transitions to `CONFIRMED`. Operational lifecycle transitions
remain deferred to resumed Phase 9.8.D; D0 deliberately exposes no status mutation.

## Schema and authority

`flight_operations` contains only `id`, `booking_id`, `status`, `created_at`, and
`updated_at`. `booking_id` is non-null, unique, and references `bookings.id` with
`ON DELETE RESTRICT`, preserving operational history. Tenant ownership is not copied:
it is derived through the canonical Booking's `operator_id` and TripRequest chain.

The database unique constraint is the final one-operation-per-booking authority. The
service additionally locks the Booking row before checking eligibility and existing
state, so concurrent callers serialize and converge on the same row. D0 operations
are immutable after creation, so no version column or blind PATCH mechanism is needed.

No passenger identity, contact data, DOB, nationality, passport, requirements,
private notes, customer amount, tax/platform split, Payment/provider reference,
client secret, refund, or payout data is persisted in the aggregate.

## Creation and transaction boundary

`BookingService.confirm` creates the operation after the Booking is marked
`CONFIRMED` and flushed, and before the existing `BOOKING_CONFIRMED` notification
intent is recorded. Booking confirmation, FlightOperation insertion, and notification
intent therefore commit or roll back together. A failure anywhere in that database
transaction cannot leave a confirmed Booking, orphan operation, or false confirmed
notification intent.

The existing payment orchestration remains after that database transaction. D0 does
not reorder, duplicate, or assume authority over the established provider-safe
capture/unknown-outcome boundary. Replayed operation creation performs no Payment or
provider action.

Rejected bookings and bookings cancelled before confirmation never receive an
operation. Cancellation after confirmation retains the operation historically and
the read projection reports the canonical Booking's `CANCELLED` state. D0 does not
invent an operational cancellation state and does not infer or initiate a refund.

Aircraft facts use the immutable Booking snapshot. Planned legs are batch-derived
from the canonical TripRequest; no independent assignment or copied leg rows are
introduced.

## Read boundary

D0 exposes only the two reads needed so resumed Phase 9.8.D is not blocked by another
backend prerequisite:

- `GET /api/v1/me/operator-operations`
- `GET /api/v1/me/operator-operations/{operation_id}`

There is no public create route, mutation route, customer route, or platform queue.
The authenticated principal's active organization derives the operator server-side;
no tenant selector is accepted. Both routes require canonical `booking.read`, making
them read-only for the five intended operator roles. A foreign detail is concealed as
404. Anonymous and customer principals are denied.

The dedicated browser-safe schema contains operation/booking identifiers and
reference, factual operation and Booking states, Booking aircraft snapshot, safe
planned legs, and timestamps only. The collection defaults to 20, accepts 1–100 with
non-negative offset, and orders deterministically by operation `created_at DESC,
id DESC`. SQL applies the bound. Booking rows are joined and all legs are fetched in
one batch, producing two queries for 1, 20, or 100 results with no N+1.

The `created_at, id` index supports deterministic queue ordering; existing Booking
operator indexing supports tenant restriction. No speculative index set or denormalized
departure field is introduced.

## Migration and compatibility

Migration `20260829_0012` has the required parent `20260828_0011` and creates exactly
one table plus its single-value PostgreSQL enum. Upgrade from 0011, downgrade back to
0011, and re-upgrade preserve existing product tables and data. ORM and migration
agree on columns, enum, timestamps, unique constraint, restrictive foreign key, and
index.

The notification four-event catalog is unchanged. Booking cancellation/refund,
Payment orchestration, unknown-outcome handling, and all existing API contracts remain
authoritative and unchanged. There is no Web production delta, dependency or lockfile
change, `.env` change, background worker, polling, SSE, WebSocket, external call, or
new secret.

## Resuming Phase 9.8.D

Phase 9.8.D may build its operator UI against the two safe reads. Any actual dispatch
or fulfillment transition must first define a factual lifecycle vocabulary, canonical
write permission, optimistic/row-lock concurrency contract, audit fields, and
transactional notification behavior. Customer or platform projections require a
separate product and privacy decision. Tail reassignment, manifests, free-form notes,
payment/refund actions, background delivery, and broad operational dashboards remain
out of D0 scope.
