# Phase 9.5.A — Customer Booking Creation and Authoritative Status

## Scope and base

Phase 9.5.A starts from canonical main
`f100f380eab0326e526ce49e57dc63ba963e8e82`. It extends the customer journey from
a real selected offer to a real Booking in `PENDING_OPERATOR_CONFIRMATION`, without
operator decisions or Payment.

## Authoritative creation contract

The browser calls `POST /api/v1/bookings` through the closed same-origin proxy with
exactly `trip_request_id` and `operator_offer_id`. It never sends `customer_id`,
`operator_id`, or `aircraft_id`. Authentication, CSRF, validated organization context,
and server-derived TripRequest ownership remain authoritative.

The backend requires a `SUBMITTED` TripRequest, its matching still-valid `SELECTED`
offer, and no active Booking. A successful 201 response is the sole source of the new
Booking. Its initial state is `PENDING_OPERATOR_CONFIRMATION`; the TripRequest remains
`SUBMITTED`, the offer remains `SELECTED`, and no Payment or provider side effect occurs.

## Duplicate and ambiguity recovery

Creation is deliberately non-idempotent. The UI combines a synchronous ref guard with
pending state so overlapping clicks issue one POST, while the backend lock and partial
unique index remain the correctness boundary. Initial Booking existence is checked with
the customer-safe trip-scoped `GET /trip-requests/{trip_request_id}/booking` read: 404
allows the eligible creation controls, 200 surfaces the authoritative Booking, and other
failures fail closed. A create 409 is never retried; the same read recovers a real Booking
into the success state and link, or the UI presents safe conflict guidance.

## Customer presentation

`/portal/bookings` uses `GET /me/bookings` and displays only the dedicated customer-safe
projection: reference, factual lifecycle status, operator legal name, aircraft snapshot,
customer total/currency, request time, and confirmation time when present. It exposes no
commercial split, internal identifiers, notes, compliance data, or payment-provider data.

The selected-offer flow uses the factual action “Create booking request” and an explicit
confirmation explaining that operator confirmation is still required and that no payment
or charge occurs in this step. No optimistic Booking is shown.

## Boundaries

There is no API, model, route-policy, migration, authentication, operator, or Payment
change and no migration `0010`. Confirm, reject, cancel, Booking-payment, Stripe, and
operator routes remain closed in the browser proxy. Phase 9.5.B owns the minimal operator
decision surface. Phase 9.6 owns Payment. Visual polish/Grok is deferred until the
functional Booking phase is complete.

## Verification

The full Web gate passes at 293 tests across 32 files. The real local Chromium E2E uses
timezone-aware dates derived comfortably into the future and passed against disposable
PostgreSQL at all required 320, 390, 768, 1024, and 1440 pixel widths. At every width it
checked the confirmation, authoritative success, and Booking-list states without unexpected
console, hydration, or horizontal-overflow errors, including practical 44px confirmation controls
and wrapping factual fields. Captured network
evidence contained exactly one `POST /bookings` with only the trip and offer ids. Database
assertions proved TripRequest `SUBMITTED`, Offer `SELECTED`, Booking count one with correct
linkage and `PENDING_OPERATOR_CONFIRMATION`, one active Booking, and Payment count zero.
