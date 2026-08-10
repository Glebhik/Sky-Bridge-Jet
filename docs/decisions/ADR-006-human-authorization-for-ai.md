# ADR-006: Human authorization boundaries for AI

## Status

Accepted — Product Owner Approved

## Context

AI improves concierge interaction but cannot replace accountable commercial or
compliance decisions.

## Decision

Use vendor-independent interfaces for AI assistance with request drafting,
clarification, option search, recommendation, comparison, Empty Leg discovery,
booking preparation, and summaries. Require explicit authorized-user action
for terms, final booking confirmation, and payment authorization.

## Consequences

AI output is validated, reviewable, and auditable. AI cannot bypass operator
confirmation or compliance controls.

## Deferred / Requires Specialist Review

Privacy, data-transfer, model-provider, consumer disclosure, security, and
applicable AI regulatory obligations require specialist review before launch.
