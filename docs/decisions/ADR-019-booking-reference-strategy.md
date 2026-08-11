# ADR-019: Booking reference strategy

## Status

Accepted

## Context

Every booking needs a stable reference suitable for future operational and
customer-facing use. It must be unique, non-secret, safe to log, stable over the
booking's life, and must not encode customer identity or expose sequential
database information.

## Decision

Each Booking carries an opaque `reference` of the form `SBJ-<16 uppercase hex
characters>`, generated from 8 cryptographically random bytes (64 bits) via
`secrets.token_hex`. It is not sequential, not derived from any customer or
passenger data, and is safe to log. Uniqueness is guaranteed authoritatively by a
database `UNIQUE` constraint on `reference`, independent of the primary key UUID.

## Consequences

The reference is a human-quotable, non-PII identifier decoupled from the internal
UUID primary key and from any row ordering. Collision probability at 64 bits is
negligible for the expected volume, and the database `UNIQUE` constraint is the
final guarantee. If future volume warrants, entropy or encoding can change
without altering the contract that the database enforces uniqueness.
