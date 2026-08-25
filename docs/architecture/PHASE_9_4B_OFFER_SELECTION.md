# Phase 9.4.B — Customer offer selection

Canonical base: `a6e875c67a8af14dd7981c9aafc75439244f2f8b` (Phase 9.4.A / PR #33 merge). Phase 9.4.B depends on the Phase 9.4.B0 customer publication boundary and the Phase 9.4.A customer-safe trip-scoped offer browser; it does not replace either contract.

## Scope and authority

Phase 9.4.B exposes one existing API operation to the authenticated customer portal: `POST /api/v1/trip-requests/{trip_request_id}/offers/{offer_id}/select`. The API remains authoritative for ownership, organization context, trip and offer lifecycle, expiry, and concurrency. The browser never sends a customer id and sends no request body.

This phase does not create a booking, initiate or collect a payment, poll, add `/portal/offers`, or expose any operator/admin mutation.

## Closed proxy boundary

The same-origin proxy adds exactly one parameterized pattern:

`["trip-requests", ":uuid", "offers", ":uuid", "select"]` with `POST` only.

Both ids must be canonical UUID path segments. Other methods return 405 for the exact route; malformed ids, adjacent verbs, missing segments, and extra segments remain closed. Existing proxy transport supplies the readable CSRF cookie as `X-CSRF-Token`, forwards the validated `X-Organization-Id`, uses same-origin credentials, and never accepts an upstream host from the browser.

## Browser contract and eligibility

`portalApi.selectOffer(tripRequestId, offerId, organizationId, signal?)` sends the exact POST with no body and returns the existing customer-safe `CustomerOffer` schema. Selection controls render only when all conditions are true:

- the trip is `SUBMITTED`;
- the candidate offer is `SUBMITTED`;
- `valid_until` parses and is strictly later than the current time;
- no visible offer is already `SELECTED`.

Unknown status, missing/invalid validity, expiry at the current instant, and any selected offer fail closed. This helper controls presentation only; it does not replace server validation.

The request has no `expected_version`. Session cookies, active organization context, and CSRF transport are inherited from the typed same-origin client. There is no customer-supplied ownership authority.

## Interaction and state

The first action opens an explicit confirmation explaining that selection creates no booking, makes no charge, and cannot be changed. “Keep comparing” cancels locally. “Select this offer” is protected by both React pending state and a synchronous ref guard, disables both confirmation controls, and emits one request even under rapid repeated activation.

There is no optimistic selection. A successful customer-safe response becomes the displayed authoritative offer and suppresses every selection control. The trip remains `SUBMITTED`. A 409 is never retried automatically; the UI shows safe conflict copy and an explicit “Refresh offers” action. Other errors show generic safe text and do not expose upstream bodies. Offer loading/errors remain isolated from the trip-detail resource.

Selection is deliberately irreversible in this phase. Booking and payment counts remain zero; selection neither creates nor starts either workflow. Polling is absent. Phase 9.4.C, Grok visual work, and the separate B1 timing gate are deferred.

## Backend and persistence boundary

`apps/api/**` is unchanged. The existing backend transaction locks the trip first, validates that the trip and offer are `SUBMITTED`, rejects effective expiry and any prior selection, and relies on the partial unique index as the final one-selected-per-trip backstop. The returned SELECTED offer is authoritative while the `TripRequest` remains `SUBMITTED`. Route policy and models remain unchanged; the route inventory remains `85 / 81 / 4`. Alembic remains at `20260813_0009`; there is no `0010` or migration.

## Verification surface

Unit and component tests cover the exact proxy matcher, CSRF/org/no-body client contract, the complete current trip-status fail-closed matrix, unknown and expired offer states, confirmation cancellation, double-click protection, pending accessibility, authoritative success, selected lock, conflict refresh, safe 403/404/network/5xx selection errors, and trip-detail organization wiring. Existing backend PostgreSQL integration tests independently cover ownership, lifecycle rejection, second selection, concurrency, and the one-selected database invariant.

The real browser E2E uses disposable PostgreSQL data and verifies two factually distinguishable published offers at five viewport sizes, the complete trip/offer selection URL, a null request body, exactly one allowed customer mutation, authoritative SELECTED presentation, the other offer remaining available, and the TripRequest remaining `SUBMITTED`. Post-run database assertions establish one selected offer and zero bookings/payments; those database checks are audit/runtime evidence rather than assertions embedded in the Playwright test itself.
