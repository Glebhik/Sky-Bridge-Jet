# ADR-012: TripRequest transaction ownership and optimistic concurrency

## Status

Accepted

## Context

Creating or transitioning a trip request commonly changes the aggregate and
related legs, passengers, and requirements. Repository-level commits could
leave partial records. Concurrent request edits must not silently overwrite
state.

## Decision

Focused application services own one explicit synchronous SQLAlchemy
transaction for each write use case. Repositories never commit. TripRequest
uses an integer SQLAlchemy version token and state commands require the
client's expected version.

## Consequences

Writes are atomic and stale writes receive a safe conflict response. This is
sufficient for the current modular monolith and avoids distributed locks,
Redis, or speculative event infrastructure. Future Quote and Booking workflows
must continue to use explicit aggregate transaction boundaries.
