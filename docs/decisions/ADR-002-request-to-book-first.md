# ADR-002: Request-to-book first; Instant Book later

## Status

Accepted — Product Owner Approved

## Context

Private aviation inventory is not uniformly available, priced, and confirmed
in real time.

## Decision

V1 uses Customer Request -> Quotes/Offers -> Customer Selects Offer -> Operator
Confirmation -> Payment/Payment Authorization -> Confirmed Booking. Inventory
can later be marked instant-book-capable only when an approved provider offers
reliable real-time availability, pricing, and confirmation.

## Consequences

Booking state is separate from quote and payment state. V1 does not promise or
implement full Instant Book for unsupported inventory.

## Deferred / Requires Specialist Review

Provider capability, contract terms, payment timing, and any customer promise
for Instant Book require provider, legal, and operational approval.
