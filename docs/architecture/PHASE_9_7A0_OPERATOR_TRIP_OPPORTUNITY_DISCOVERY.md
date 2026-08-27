# Phase 9.7.A0 — Operator-safe trip opportunity discovery

Canonical base: `c7d7dac0b26febbde0950d87812e417872b92b72`.

## Purpose and route

Phase 9.7.A0 adds one API-only prerequisite for the later operator Offer UI:

`GET /api/v1/me/operator-opportunities?limit=20&offset=0`

The collection is authenticated, read-only, capped at 100 rows, and scoped from the
validated active OPERATOR organization. It accepts no `operator_id`. The Web proxy and
all Offer mutations remain unchanged.

## Authorization and eligibility

The route uses the existing `offer.read` permission. The canonical matrix grants it to
`OPERATOR_ADMIN`, `OPERATOR_SALES`, `OPERATOR_OPERATIONS`, `OPERATOR_FINANCE`, and
`OPERATOR_COMPLIANCE`; customer and non-operator contexts fail closed. This intentionally
records actual server policy rather than introducing a UI-specific permission.

Only operators whose operator-level admission and required evidence pass the existing
`ComplianceEvaluator` see opportunities. Aircraft authorization remains a later,
aircraft-specific check when an Offer is created. An ineligible operator receives an empty
collection; confidential compliance reasons are not exposed.

Only `SUBMITTED` TripRequests are selected because that is the sole state accepted by the
existing Offer create/submit contract. There is no invented geography, aircraft matching,
subscription, targeting, or ranking.

## Privacy projection

The dedicated response contains only:

- `trip_request_id`, persisted `SUBMITTED` status, and `created_at`;
- ordered legs: sequence, origin/destination ICAO code, departure time, passenger count;
- the active operator's own Offer IDs and effective lifecycle statuses.

Multiple own Offers are possible when different owned aircraft are offered, so the contract
uses a deterministic `own_offers` list instead of a misleading singular flag. Foreign Offer
existence, IDs, status, pricing, notes, and aircraft are never projected.

The projection never loads or returns customer identity, organization, email, phone,
passenger identity/IDs, DOB, nationality, passport/document data, raw requirements,
special-assistance or private notes, payment/provider data, platform fee, tax, customer
total, or internal audit metadata. Baggage, catering, transport, pet, assistance, and
customer-note fields are deliberately deferred: they are not required for the minimal A0
discovery contract and some may contain sensitive free text.

## Query, ordering, and mutation properties

Eligibility and filtering happen before materialization. The opportunity SQL predicate is
`TripRequest.status == SUBMITTED`; ordering is `created_at ASC, id ASC`; SQL applies `LIMIT`
and `OFFSET`. The service executes a fixed six statements for a non-empty eligible page:
one admission read, two required-evidence reads, one bounded TripRequest read, one batched
leg/airport eager-load, and one batched active-operator Offer read. The count does not grow
per card; there is no N+1.

The GET performs no writes. It creates no Offer, Booking, Payment, PaymentOperation,
webhook, compliance, or audit state. It adds no cache, polling, realtime channel, worker,
dependency, provider call, or background processing.

## Contract and restart boundary

Route inventory changes from `87 / 83 / 4` to `88 / 84 / 4`. Alembic remains
`20260827_0010`; there is no `0011`. Phase 9.7.A may restart from this contract by adding an
operator Web consumer and exact proxy entries for the separately audited Offer workflow.
It must retain server-derived organization authority and this privacy boundary.

Deferred: Offer UI, dashboards, notifications, scheduling, aircraft matching, geography
targeting, cancellation UI, payment authority, Stripe activation, and Phase 9.8.
