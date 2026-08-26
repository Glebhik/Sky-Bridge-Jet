# Phase 9.4.C — Offers landing, bounded freshness, and lifecycle E2E

Canonical base: `c6e852327f7bd5a3c43372500484934c46004e01` (Phase 9.4.B / PR #34 merge). Phase 9.4.B0 supplies the customer publication boundary, 9.4.A supplies customer-safe trip-scoped comparison, and 9.4.B supplies explicit server-authoritative selection.

## Purpose and landing architecture

`/portal/offers` is a real trip-navigation page. It performs exactly one organization-scoped `GET /me/trip-requests`, orders the returned requests by `created_at` descending and then `id` descending, and links each factual request to `/portal/trip-requests/{id}`. It shows real request status, request handle, leg/departure summary, and requested time. Loading, missing customer context, safe error, empty, and populated states are explicit.

There is deliberately no customer-wide offers endpoint. The landing never calls `listTripRequestOffers`, never issues one offer request per row, and never invents offer counts, prices, operator, aircraft, ranking, or availability. Offer reads remain trip-detail-scoped.

## Bounded freshness contract

The trip detail uses one small local offer-read controller. After the initial authoritative GET succeeds, automatic refresh is eligible only while the TripRequest status is exactly `SUBMITTED`, no returned offer is `SELECTED`, and the document is visible. Unknown and every non-`SUBMITTED` status fail closed.

Eligible details use exactly one 30-second interval. Hiding the document removes that interval. A hidden-to-visible transition or window focus triggers one immediate authoritative GET when eligible. Selection, a terminal/non-submitted trip status, route or organization identity change, or unmount stops automatic refresh. A selected offer may still be refreshed manually, but it is never polled indefinitely.

The controller allows one in-flight read. Interval, focus, visibility, and manual requests share the same promise and cannot overlap. Every request uses `AbortController`; unmount and trip/organization identity changes abort the active read and advance a generation token so a stale completion cannot overwrite the new resource.

Background failure retains the last known offers and shows the safe message “Couldn’t refresh offers. Showing the last known information.” An unchanged failure keeps the existing live region mounted instead of repeatedly announcing identical text every polling interval; recovery clears it so a later new failure can be announced. Raw upstream detail is never rendered. The native manual “Refresh offers” button is GET-only and disabled while a read is active. Initial failure remains the isolated full offer error. The existing explicit 409 refresh uses this same safe read path and is never an automatic mutation retry.

Authoritative refresh is the idle-expiry mechanism: once the API projects an elapsed persisted `SUBMITTED` offer as effective `EXPIRED`, the card displays “Expired” and its Select action disappears. The browser does not persist or fabricate expiry.

## Preserved boundaries

Money/currency formatting, deterministic offer comparison, customer-safe fields, explicit selection confirmation, synchronous duplicate guard, no-body selection POST, 409 handling, and selected lock remain unchanged in business meaning. Timers perform GET reads only and never select. There is no WebSocket, EventSource, SSE, subscription system, server push, global state, or worker.

The TripRequest remains `SUBMITTED` after offer selection. Phase 9.4.C creates neither Booking nor Payment and exposes no booking/payment action. `apps/api/**`, route policy, models, and persistence are unchanged; route inventory remains `85 / 81 / 4`, Alembic head remains `20260813_0009`, and there is no `0010` or migration.

## Verification

Component tests use fake timers and browser events to cover the exact cadence, one GET per tick, overlap prevention, hidden pause, visible/focus refresh, selected and non-submitted stop gates, abort on unmount/identity change, late stale-response rejection, non-repeating failure announcements through recovery, safe retained-data failure, manual deduplication, expiry correction, absence of timer mutation, 409 refresh, and selected lock. Landing tests cover all honest states, deterministic ordering, factual links/status, forbidden commercial claims, and zero trip-scoped offer calls. The tracked real lifecycle also checks representative mobile/desktop landing widths and logout denial.

The local real lifecycle run uses task-specific disposable PostgreSQL and synthetic customer/operator/aircraft/offer records only. Its evidence covers landing-to-detail navigation, DRAFT invisibility, a newly published offer appearing after focus/visibility refresh without navigation, one no-body selection POST, persistent selected state, TripRequest `SUBMITTED`, one selected offer, and zero bookings/payments. Runtime and database evidence is recorded in the Phase 9.4.C implementation report; no credentials are retained.

Grok visual polish is a separate next activity after audit/commit. Phase 9.5 Booking and the separate B1 timing gate are not part of this phase.
