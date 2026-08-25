# Phase 9.4.A — Customer offer reads and factual comparison

## Scope

Canonical base: `f257170f77ccc7bb7e337003686ea28a0d860dfc`, the Phase 9.4.B0 merge. B0 is the server-side prerequisite: customer offer lists publish only persisted `SUBMITTED` and `SELECTED` offers; elapsed persisted `SUBMITTED` offers are projected as effective `EXPIRED`. Persisted `DRAFT` and `WITHDRAWN` remain hidden.

This slice is Web-only and read-only. It adds the single closed same-origin proxy pattern `GET trip-requests/:uuid/offers`, a customer-safe browser type, and `portalApi.listTripRequestOffers`. No select route or client method, operator route, booking/payment mutation, polling, storage, direct upstream access, or authorization forwarding is introduced.

## Customer contract and presentation

The browser type mirrors only the customer projection: IDs for the offer/trip, effective status, currency, tax/total minor amounts, validity, factual operator legal name, snapshotted aircraft registration/manufacturer/model/category, included/excluded services, cancellation policy, safe timestamps, and the `customer` audience discriminator. Operator/aircraft IDs, operator amount, platform fee, operator notes, compliance/admission and provider/admin fields are absent.

Money stays integer minor units for comparison and is divided by 100 only for `Intl.NumberFormat` presentation. Offers group deterministically by currency, then total minor amount, validity, creation time, and stable ID. No FX comparison or “best/cheapest/recommended” claim is made.

The real trip detail owns the comparison section. It independently loads offers so a failure cannot destroy the trip request. It represents loading, empty, error, one/many, mixed-currency, available, expired, selected, and fail-closed unknown status states. Cards show factual price, tax, operator, aircraft, validity, services, and cancellation policy. Capacity, cabin class, arrival/duration, repositioning, ratings and savings are not available and are not displayed.

There is deliberately no Select CTA, Booking/Payment action, polling, global `/portal/offers` aggregation, offer-detail route, or fake data. Phase 9.4.B owns selection. Phase 9.4.C owns polling and the offers landing/inbox decision. Grok visual polish and the B1 timing gate remain separate.

## Invariants and verification

`apps/api/**`, route policy, database models and Alembic remain byte-identical; route inventory remains `85 / 81 / 4`, Alembic head remains `20260813_0009`, and there is no `0010`. Proxy, client, helpers, components and page integration tests cover the closed route, safe request behavior, currency-aware ordering, status semantics, loading/empty/error isolation, factual cards, long content, mixed currencies and absence of mutation controls. Local real-read E2E evidence verifies published visibility, DRAFT invisibility, effective expiry, safe fields, and zero selection/booking/payment side effects.
