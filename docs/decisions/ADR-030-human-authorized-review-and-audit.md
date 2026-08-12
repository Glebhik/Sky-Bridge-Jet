# ADR-030: Human-authorized compliance review and audit model

## Status

Accepted

## Context

Compliance decisions (operator admission, evidence verification, aircraft
authorization, suspension restoration) are high-consequence. Per ADR-006, AI must
not autonomously make accountable compliance or commercial decisions, and every
decision must be auditable. Authentication remains deferred.

## Decision

Review commands (approve/reject/suspend/restore/begin-review, verify/reject
evidence) require an `actor_type` that is human-authorized — `PLATFORM_REVIEWER`
or `PRODUCT_OWNER`; `SYSTEM` and `OPERATOR` are rejected. This is a provider-
neutral abstraction: because authentication is deferred, an unauthenticated API
call does **not** by itself prove human authorization, and the documentation says
so — a future auth layer binds `actor_type` to a real authenticated reviewer.
Operator self-service actions (create/submit) are separated from platform review
actions.

Every material change appends a row to `compliance_audit_events` (entity type and
id, action, previous/new status, actor type and optional non-PII reference, reason
code, bounded optional note, timestamp). Audit rows are written only by inserts;
the service never updates or deletes them. No secrets and no raw document contents
are stored or logged.

## Consequences

Decisions are attributable and auditable, and the architecture is ready for real
authenticated human reviewers without redesign. The software does not claim that
an unauthenticated call constitutes human authorization.
