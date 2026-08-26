# Phase 9.6.A0 — Authoritative Customer Payment Discovery

Phase 9.6.A0 is based on `39b87fbf9efc9a9a1de8aa49a1166a83e31814ff` and
unblocks the deferred customer Payment UX without adding that UX itself.

The legacy `/me/bookings` and `/me/payments` collections are independently
paginated and ordered. Absence from a Payment page therefore could not prove that
a displayed Booking had no Payment. The existing `GET /api/v1/me/payments` now
accepts one to 100 repeated `booking_id` query parameters in lowercase canonical
hyphenated UUID form. Filtered mode
rejects `limit` and `offset`; all matching Payments for the requested set are
returned, ordered by Payment creation time and ID. Duplicate IDs are normalized.

The query joins Payment to Booking and TripRequest and applies both active-customer
ownership and requested Booking IDs in one SQL statement before materialization.
Foreign and unknown IDs are indistinguishable from owned Bookings without Payments:
they contribute no row. The response remains the existing customer-safe projection.
No internal allocation, provider metadata, operation ledger, idempotency key, or
customer/operator identity is exposed.

For each owned requested Booking ID absent from the response, no Payment existed in
the database snapshot observed by that request. This is not a permanent guarantee:
a concurrent transaction may create one later, and B0 uniqueness/idempotency remains
the final mutation authority. Unfiltered calls retain legacy bounded pagination.

The route inventory remains 87/83/4. Alembic remains `20260813_0009`; there is no
migration. The seam is read-only, performs no provider call, and does not alter B0.
No Web UX, Stripe integration, capture, void, refund, polling, dependency, or lockfile
change is included. After A0 is merged, Phase 9.6.A may submit the displayed Booking
set once, join results by `booking_id`, and treat owned requested absence as
authoritative for that request snapshot without N+1 reads.
