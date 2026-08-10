# ADR-009: Synchronous SQLAlchemy foundation

## Status

Accepted

## Decision

Use SQLAlchemy 2.x synchronously for the Phase 1 API, including engine,
request-scoped sessions, readiness checks, and Alembic migrations.

## Rationale

The initial API has no concurrent provider integrations or database-heavy
business workflows. FastAPI runs synchronous routes in its thread pool, and one
consistent synchronous model makes transactions and migrations straightforward.

## Consequences

Async SQLAlchemy must not be introduced alongside this session pattern. Revisit
the choice only through a deliberate migration when a future implementation has
a demonstrated need.
