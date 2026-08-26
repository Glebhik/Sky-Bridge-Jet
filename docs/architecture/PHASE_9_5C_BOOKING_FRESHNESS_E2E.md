# Phase 9.5.C — Booking freshness and complete lifecycle E2E

Canonical base: `205c65c5cf7b5a7dd057530c992750b0afa5b134`.

## Purpose and read boundary

This web-only slice completes the customer-visible Booking decision lifecycle. The customer
Booking list uses the existing `GET /api/v1/me/bookings` customer-safe projection because it is
the smallest read that refreshes the whole currently visible bounded page in one request. It is
already scoped by the authenticated principal and validated active customer organization. The
existing trip-scoped Booking read remains limited to Booking-create discovery and 409 recovery;
no new endpoint, backend code, route, model, or migration is introduced.

The projection includes the Booking reference and status, trip and selected-offer references,
customer total/tax and currency, factual operator and aircraft snapshots, customer-safe
cancellation fields, and timestamps. It structurally omits operator/customer internal IDs,
operator amount, platform fee, confirmation reference/note, operator rejection note, compliance
metadata, and payment-provider data. The list currently refreshes the API's bounded default page;
this phase does not build global Booking-history synchronization.

## Bounded freshness controller

`use-booking-freshness.ts` owns one controller for `/portal/bookings`, never one controller per
card. Automatic freshness is eligible only while the last authoritative list contains
`PENDING_OPERATOR_CONFIRMATION`. `CONFIRMED`, `REJECTED`, and `CANCELLED` are terminal; unknown
future values fail closed. The cadence is exactly 30,000 ms. A hidden document stops the interval;
becoming visible performs one immediate read and restores the bounded cadence. Window focus also
performs one immediate read while eligible. Terminal or context-free state has no automatic read.

Interval, focus, visibility, and the native **Refresh status** button share one in-flight GET.
Every request uses an `AbortController`; unmount or active-organization/resource identity change
aborts the active request. A resource identity plus generation token prevents an obsolete late
response from committing even if abort is not honoured by the transport. A successful terminal
response stops automatic interval, focus, and visibility freshness.

A transient background failure retains the last known Booking list and shows the fixed factual
message “Booking status could not be refreshed.” Raw error bodies are never rendered. The same
live-region node and string remain mounted across an identical repeated failure instead of being
removed and re-added; a later successful read clears it. The page exposes `aria-busy`, disables
the refresh control in flight, and uses a restrained polite status region. Text, not colour alone,
communicates every status. Controls retain the portal's 44 px minimum target and stack on narrow
viewports.

## Customer and operator lifecycle

The customer list presents `CONFIRMED` as “Confirmed by the operator” and `REJECTED` as “The
operator could not confirm this booking”. It never implies payment, charging, capture, ticketing,
or refund, and it never invents a rejection reason. Booking-create success uses its authoritative
201/read result without another POST and directs the customer to `/portal/bookings`; it does not
own a second timer. The operator queue and confirm/reject transaction remain unchanged.

The complete real lifecycle gate covers two separate Bookings. In the confirm fixture, customer
creation and selection lead to one Pending Booking, an authenticated operator confirms it in a
separate browser context, and the already-open customer list obtains `CONFIRMED` through an
additional GET without full-page navigation. The reject fixture independently reaches Pending,
the operator rejects with `AIRCRAFT_UNAVAILABLE`, and the open customer list obtains `REJECTED`.
Both retain `TripRequest=SUBMITTED`, `Offer=SELECTED`, exactly one Booking, and zero Payments. Real
runtime evidence and any environment limitation are reported without substituting synthetic
claims. Deterministic fake-timer tests prove the exact 30,000 ms cadence. The real browser gate
exercises the focus lifecycle, but true OS-level document visibility is not independently
controlled or reproduced there; hidden/visible behavior is covered deterministically by tests
that control `document.visibilityState` and dispatch `visibilitychange`.

Customer responsive runtime is independently exercised at `320×568`, `390×844`, `768×1024`,
`1024×768`, and `1440×900` for Pending, Refreshing, transient warning, Confirmed, and Rejected
presentation states.

## Explicit exclusions and invariants

There is no WebSocket, SSE, EventSource, service worker, generalized subscription framework,
payment, Stripe, authorization/capture/refund action, notification, or operator polling expansion.
`apps/api/**` remains byte-identical; route inventory remains `86 registered / 82 OpenAPI / 4
documentation`, Alembic remains `20260813_0009`, and there is no `0010`. The same-origin proxy and
customer/operator authority boundaries are unchanged.

Phase 9.5 is functionally complete only after this implementation passes independent audit and
closure. Grok remains deferred until functional closure. Phase 9.6 Payments is deferred, as are
Phases 9.7 and 9.8. The separate B1 timing gate remains separate from this freshness slice.
