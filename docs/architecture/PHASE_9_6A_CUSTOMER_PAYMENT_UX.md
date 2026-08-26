# Phase 9.6.A — Customer Payment UX

Phase 9.6.A is implemented from canonical base
`c5f28b1017d605a9576d1e072baaa3804791a0d9`. It depends on the merged B0
customer initiation boundary and A0 authoritative discovery seam.

`/portal/bookings` first loads the displayed customer-safe Booking collection and then
sends every displayed Booking ID in one repeated-`booking_id` request to
`GET /api/proxy/me/payments`. Payments are joined to cards only by `booking_id`; there is
no positional, amount, reference, operator, or timestamp inference and no request per card.
For an owned requested Booking, absence is authoritative for the database snapshot observed
by A0. A concurrent transaction may still create a Payment afterward, so B0 remains final
mutation authority.

The proxy adds exactly one closed mutation pattern:
`POST /api/proxy/bookings/:canonical-uuid/payment/initiate`. The browser body is exactly
`{"idempotency_key":"<opaque-key>"}`. CSRF and the validated active-organization header
use the existing same-origin client. Customer, operator, amount, currency, and provider are
derived by the API. The response is the existing customer-safe Payment schema; provider
references, operations, internal commercial splits, and client secrets never reach the UI.

One `crypto.randomUUID()` key is created per logical attempt and kept only in memory. Rapid
activation is stopped synchronously and by pending UI state. An unknown transport outcome
retains the same key for an explicit same-attempt retry; a resolved authorization failure
permits a new key. Success and organization changes invalidate the attempt. Keys are never
stored in URLs, cookies, localStorage, sessionStorage, or analytics.

The independent audit found and the closure repair removed an unknown-outcome escape that
previously left the ordinary new-attempt CTA reachable. While an unresolved key exists, the
UI now exposes only authoritative refresh and explicit same-attempt retry. The hook also
fails closed if any caller requests a normal new attempt while that key exists, or requests
a same-attempt retry when no unresolved key exists. An authoritative refresh clears the
attempt only when it actually finds a Payment; organization changes invalidate the old key.

The B0 response is authoritative and stale reads cannot overwrite it: starting a mutation
aborts the active discovery and advances its generation. A 409 causes no automatic POST and
exactly one authoritative collection refresh. Other read failures keep Booking data visible
but fail closed by hiding authorization eligibility. Payment freshness is initial discovery,
the B0 response, manual refresh, and the single 409 refresh; Phase 9.6.A adds no Payment
polling, focus timer, WebSocket, or SSE.

Copy keeps Booking and Payment lifecycles separate. `AUTHORIZED` is “Payment authorized”
and explicitly not captured; it does not mean the operator confirmed the Booking. Captured,
cancelled, partial-refund, refund, failure, action-required, and unknown states are factual
and read-only. Existing integer minor-unit formatting supports EUR, GBP, and USD with no FX
or cross-currency aggregation.

Acceptance uses the deterministic FAKE provider only. No Stripe SDK, Payment Element, card
data, 3DS UI, checkout redirect, capture, void, refund, settlement, or provider network call
is introduced. API production code, routes (`87/83/4`), and Alembic
`20260813_0009` remain unchanged with no `0010`. Phase 9.6.B and 9.6.C remain deferred.

Component and page tests cover the closed proxy, exact client body, authoritative bulk join,
confirmation, double-action protection, idempotency lifecycle, 409 recovery, unknown network
outcome, stale-read rejection, organization invalidation, customer-safe status copy, read
failure isolation, accessibility semantics, and narrow responsive controls. Real local
FAKE-provider acceptance verifies one POST, the authorization ledger, and the unchanged
Booking/Offer/Trip state separation.

Final acceptance evidence: Web is `346/346` tests in `35` files and API remains `531/531`.
The real-browser run displayed two Bookings, issued one filtered Payment GET containing both
repeated Booking IDs, joined one existing Payment to the correct card, and left the other card
eligible. Each confirmed logical action emitted exactly one initiation POST. Captured request
evidence contained only `idempotency_key`, included CSRF and active-organization headers, and
contained no bearer header. PostgreSQL showed `SUBMITTED` / `SELECTED` /
`PENDING_OPERATOR_CONFIRMATION` with an `AUTHORIZED` Payment, authorized amount equal to the
Booking total, zero captured/refunded amount, and one successful `AUTHORIZE` ledger entry with
no capture, void, or refund operation. Browser checks at `320×568`, `390×844`, `768×1024`,
`1024×768`, and `1440×900` found no horizontal overflow; console/hydration checks were clean.
