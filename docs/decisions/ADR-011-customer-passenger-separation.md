# ADR-011: Customer and Passenger are separate Phase 2 entities

## Status

Accepted

## Context

The customer initiating a private-aviation request may not be travelling. A
request can include family, colleagues, guests, or executives. Treating the
customer as the passenger would duplicate data and make ownership unclear.

## Decision

Model Customer as a business-domain party and Passenger as a separately owned
traveller. A Passenger belongs to one Customer in Phase 2, while an explicit
TripPassenger association connects a TripRequest to its travellers. Customer is
not an identity or authentication principal.

## Consequences

Passenger data remains minimized and is not copied into the trip aggregate.
This supports customer-as-passenger and multi-passenger trips without storing
passport, document, medical, or other unnecessary sensitive information.
Delegated ownership, authentication, and cross-organization relationships
remain deferred.
