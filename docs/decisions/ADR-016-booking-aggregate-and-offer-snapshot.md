# ADR-016: Booking aggregate and selected-offer commercial snapshot

## Status

Accepted

## Context

A selected operator offer expresses commercial intent but is not a confirmed
booking. Phase 4 needs a durable record of the booking workflow arising from one
selected offer. That record must preserve the commercial facts that caused it to
exist, even if mutable reference data (operators, aircraft) changes later, and it
must not become a competing source of truth with the Phase 3 selection.

## Decision

Introduce a `Booking` aggregate in a new `bookings` bounded-context module. One
Booking corresponds to one selected offer's workflow. The Booking stores an
**immutable commercial snapshot** copied from the selected offer at creation:
currency, operator amount, platform fee, tax, total (integer minor units,
ADR-013), the offer's validity, and operator/aircraft identity strings.

Database integrity is enforced by a single composite foreign key
`bookings(operator_offer_id, trip_request_id, operator_id, aircraft_id) ->
operator_offers(id, trip_request_id, operator_id, aircraft_id)`, so a booking can
only reference an offer while agreeing with it on trip, operator, and aircraft.
Monetary non-negativity, total consistency, and supported currency are enforced
by `CHECK` constraints, mirroring the offer.

The Phase 3 selected offer is left untouched, and the Phase 2 `TripRequest`
lifecycle is not mutated: the Booking is the authoritative source of booking
state. No passenger PII is copied into the Booking.

## Consequences

Booking history is tamper-evident and self-contained; queries for historical
commercial truth never depend on joining mutable current-state tables. There is
no `TripRequest.BOOKED` activation, avoiding two competing sources of truth. A
future renegotiation must be modelled explicitly rather than editing a booking.
