# Phase 9.3.C — Trip management and dashboard

Phase 9.3.C is the final functional Phase 9.3 slice. It is based on
`2c6b7a5bb156e98d3fabdfbe084fa3b0a25330c9` and adds customer trip-request cancellation plus
a factual portal dashboard. It does not begin Phase 9.4.

## Authoritative cancellation contract

The existing backend transition table was audited before the web implementation:

| Current status | Customer cancellation | Result |
| --- | --- | --- |
| `DRAFT` | allowed | `CANCELLED` |
| `SUBMITTED` | allowed | `CANCELLED` |
| `QUOTING` | rejected with 409 | unchanged |
| `QUOTES_AVAILABLE` | rejected with 409 | unchanged |
| `QUOTE_SELECTED` | rejected with 409 | unchanged |
| `BOOKED` | rejected with 409 | unchanged |
| `CANCELLED` | rejected with 409 | unchanged |
| `EXPIRED` | rejected with 409 | unchanged |

The closed same-origin proxy adds only `POST trip-requests/:uuid/cancel`. The UUID segment,
segment count, literal `cancel` suffix, and POST method must all match; this is not a prefix,
wildcard, catch-all, or direct-upstream route. Existing CSRF, cookie, organization-header, and
response-sanitization rules remain in force. Browser code neither forwards `Authorization` nor
supplies `customer_id`.

The client sends `VersionedTripCommand` as `{ "expected_version": <last real version> }`. It
uses the version returned with the displayed request and never fabricates or increments a
version. The detail page offers cancellation only for `DRAFT` and `SUBMITTED`, requires an
explicit confirmation, and uses a synchronous in-flight guard in addition to disabled/busy UI
to prevent duplicate POSTs. It does not optimistically invent `CANCELLED`: only the real
backend response replaces the displayed request. A 409 shows a changed-request state and an
explicit refresh action, which clears the response overlay and re-reads authoritative state.
404 and other failures use safe messages without exposing backend bodies.

## Dashboard model

The dashboard reads the existing customer-scoped `GET /me/trip-requests`; there is no new
backend aggregation endpoint and no fake pricing, quote, aircraft, booking, or payment metric.
The four counts are Total, Active, Submitted, and Cancelled.

**Active** is an explicit allowlist: `DRAFT`, `SUBMITTED`, `QUOTING`, `QUOTES_AVAILABLE`, and
`QUOTE_SELECTED`. `BOOKED`, `CANCELLED`, and `EXPIRED` are not active. An unknown future status
is also not counted until deliberately classified. Submitted and Cancelled are exact-status
counts, while Total is the returned list length.

Recent requests are the five newest by `created_at` descending, with descending request id as
a deterministic tie-breaker. Each links to the same detail route and uses the same handle,
status badge, and leg summary conventions as list/detail. Dashboard, list, and detail all read
the same customer trip-request data; after a real cancellation, revisiting dashboard/list
reflects `CANCELLED` and removes the request from Active. The dashboard covers no-customer,
loading, error, empty, and populated states and provides a real New trip request link.

## Verification boundary and evidence

The full disposable local journey passed:

`Dashboard → New trip request → Passenger → DRAFT → submit the same request → SUBMITTED →`
`Dashboard → same-request detail → explicit Cancel → CANCELLED → Dashboard → logout`.

Network capture established that passenger and trip-create payloads contain no `customer_id`;
there was exactly one TripRequest create, one submit, and one successful cancel; submit and
cancel used the same UUID; cancel used the real version `2`; and there were no offer, booking,
or payment mutations. Database assertions established exactly one TripRequest, Passenger,
TripLeg, and TripPassenger association with authoritative ownership, final status `CANCELLED`,
version progression `1 → 2 → 3`, and zero offers, bookings, and payments.

Responsive runtime coverage passed at 320×568, 390×844, 768×1024, 1024×768, and 1440×900 for
dashboard, list, create, cancellable detail, confirmation, and cancelled detail, including
overflow, keyboard focus-visible, mobile navigation, and console/hydration checks. The pending
state's disabled and `aria-busy` semantics and the synchronous duplicate-submit guard are
covered deterministically by component tests.

The production backend boundary is hard: `apps/api/**` remains byte-identical to the base;
route inventory remains **85 normalized / 81 OpenAPI / 4 docs**; Alembic head remains
`20260813_0009`; there is no `0010`, migration, route-policy, backend-route, or DB-model change.
The API baseline remains 500 tests.

## Deferred work

There is no Phase 9.4, operator/admin UI, offer selection, booking/payment mutation, passenger
roster, or profile expansion here. Grok remains deferred until after Phase 9.3.C is merged.
The B1 production email-timing gate remains a separate hardening item.
