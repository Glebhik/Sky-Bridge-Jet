# Phase 9.7.B0 — Operator-safe Booking history and detail reads

## Purpose and base

This API-only prerequisite is based on `2a7093720f092233bc1511d5511af5447f88875c`. Phase 9.7.B could not safely build history from the pending-only `/me/operator-bookings` queue or expose the generic internal Booking detail. B0 adds two dedicated read seams without changing either existing contract.

## Routes and authority

- `GET /api/v1/me/operator-bookings/history`
- `GET /api/v1/me/operator-bookings/{booking_id}`

Both require `booking.read`. The complete read-role matrix is OPERATOR_ADMIN, OPERATOR_SALES, OPERATOR_OPERATIONS, OPERATOR_FINANCE and OPERATOR_COMPLIANCE. Only ADMIN and OPERATIONS retain the separate `booking.decide` permission. The authenticated principal must select an active OPERATOR organization. The server resolves its operator and applies `Booking.operator_id == active_operator_id` in SQL. A UUID identifies a candidate Booking but grants no authority; a foreign Booking is concealed with 404.

## Shared safe projection

History and detail return `OperatorBookingReadView`. It contains the opaque Booking/reference identifiers, canonical status, own operator amount/currency, immutable aircraft identity snapshot, route legs, and canonical created/updated/confirmed/rejected/cancelled timestamps. Legs contain only sequence, ICAO endpoints, departure time, and passenger count.

The projection structurally omits customer identity and organization data, passenger identity, DOB, nationality, passport, requirements and private notes; rejection/confirmation/cancellation notes and reasons; platform fee, tax decomposition and customer total; Payment, PaymentOperation, provider, idempotency, refund, compliance evidence and audit internals. Tax is deliberately omitted because operator operations do not require that decomposition.

## Collection contract and performance

History accepts `limit` (default 20, range 1–100), `offset` (minimum 0), and an optional canonical `BookingStatus` query named `status`. Filtering occurs in SQL before pagination. Results use `created_at DESC, id DESC`, including deterministic ties. The canonical states are PENDING_OPERATOR_CONFIRMATION, CONFIRMED, REJECTED and CANCELLED.

The collection performs one bounded Booking query and one batch leg query, independent of page size. Detail performs one operator-scoped Booking query and one batch-shaped leg query. Neither path loads Offer, Aircraft, Customer, Payment or per-row relationships, and neither path flushes, commits, emits events or writes audit rows.

## Preserved contracts

`GET /me/operator-bookings` remains the oldest-first pending decision queue. Existing confirm/reject behavior is unchanged. `GET /bookings/{booking_id}` remains the trusted audience-aware generic/internal route and is not reused by browser-facing operator code.

No Web source, proxy matcher, dependency, database schema or migration changes in B0. Route inventory becomes 92 registered / 88 OpenAPI operations / 4 documentation routes. Alembic remains `20260827_0010` with no `0011`.

## Phase 9.7.B restart contract

The subsequent Web phase may expose only these exact GET paths through the closed same-origin proxy, send the selected organization header, use bounded server pagination/status filtering, render history without per-card detail calls, and request detail only after explicit navigation. Cancellation/refund UI, passenger manifests, scheduling, payments, realtime and later phases remain deferred.
