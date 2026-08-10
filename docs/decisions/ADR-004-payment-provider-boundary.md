# ADR-004: PaymentProvider boundary and deferred production payment model

## Status

Accepted — Product Owner Approved

## Context

Sky Bridge Jet must orchestrate customer payment without assuming banking,
escrow, card storage, settlement, treasury, or merchant-of-record duties.

## Decision

Use a `PaymentProvider` port with an initial `MockPaymentProvider`. Keep booking
and payment state separate, never store raw card credentials, and never mark a
booking paid without confirmed provider state.

## Consequences

Payment integration is replaceable and can be tested without live credentials.
No production payment or settlement implementation is implied by this decision.

## Deferred / Requires Specialist Review

Legal, accounting, payment-provider, and regulatory review must approve the
merchant-of-record, agency, settlement, refunds, payment flows, and compliance
scope before production.
