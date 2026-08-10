# ADR-005: Empty Legs as a first-class domain concept

## Status

Accepted — Product Owner Approved

## Context

Repositioning flights are a strategic customer opportunity and are not merely
discounted ordinary bookings.

## Decision

Model `EmptyLeg` independently with operator, aircraft, origin, destination,
departure window, available seats, price, currency, flexibility, availability,
provenance, and lifecycle. V1 may use seeded, manually entered, or mock
inventory.

## Consequences

Customers can discover and request/book eligible Empty Legs while later
operator, broker, marketplace, and real-time feeds fit through adapters.

## Deferred / Requires Specialist Review

Provider-feed rights, inventory accuracy obligations, commercial terms, and
applicable aviation/legal requirements require specialist review.
