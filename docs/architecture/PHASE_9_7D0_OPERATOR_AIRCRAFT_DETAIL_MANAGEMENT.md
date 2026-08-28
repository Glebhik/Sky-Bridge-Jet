# Phase 9.7.D0 — Operator-safe aircraft detail and creation

## Context

Phase 9.7.D was blocked at canonical base
`f9f88755154ff162bfc6ed3ca3555a3dd016d646`: the A1 aircraft collection was
safe, but the only detail and create operations were generic internal contracts.
D0 supplies the smallest browser-facing backend prerequisite. It does not add Web
code, a migration, or new aircraft/compliance domain states.

## Active-operator API

- `GET /api/v1/me/operator-aircraft/{aircraft_id}` requires `OPERATOR_READ`.
- `POST /api/v1/me/operator-aircraft` requires `OPERATOR_MANAGE`, which the
  canonical role matrix grants only to `OPERATOR_ADMIN` among operator roles.
- Both routes derive the operator from the authenticated principal and validated
  active OPERATOR organization. A browser never selects `operator_id`.
- Unknown and foreign aircraft are indistinguishable `404` responses.

The response reuses the safe A1 projection exactly: `id`, `registration`,
`manufacturer`, `model`, `category`, `passenger_capacity`, `status`, and computed
`eligible`. It excludes ownership identifiers, timestamps, compliance evidence and
reviews, customer/passenger data, bookings, payments, providers, and audit internals.

The closed create schema accepts only registration, manufacturer, model, category,
and passenger capacity. The router constructs the existing canonical internal
`AircraftCreate` command with the server-derived operator and delegates transaction
ownership and domain validation to `OperatorService.create_aircraft`.

## Update and status decision

D0 intentionally does not introduce PATCH or status commands. Although the persisted
enum contains `ACTIVE` and `INACTIVE`, the current domain has no canonical update
command, transition rules, or concurrency contract. Detail plus server-derived create
is a useful Phase 9.7.D inventory MVP; mutation beyond creation remains deferred until
those semantics are designed explicitly. No maintenance, grounding, availability, or
dispatch states are invented.

## Compliance and offer authority

`eligible` remains computed from canonical operator admission, evidence, and aircraft
authorization. Create cannot set or change it. A newly created owned aircraft is not
eligible until the independent compliance workflow authorizes it, and Offer creation
continues to reject it. D0 neither approves evidence nor changes review state.

## Isolation, query bounds, and preserved contracts

The detail repository query includes both aircraft and server-derived operator IDs,
so cross-tenant identifiers disclose no aircraft metadata. Eligibility uses a fixed,
bounded query shape and never materializes evidence history. Create uses the existing
explicit service transaction; failed validation or uniqueness checks cannot partially
persist an aircraft.

The bounded, deterministic A1 collection remains unchanged. Generic
`GET /api/v1/aircraft/{aircraft_id}` and `POST /api/v1/aircraft` remain available and
unchanged for their existing legitimate audiences. Every new operation has an exact
authenticated route policy; there is no wildcard or public exposure.

## Release invariants

- Route inventory: 95 registered, 91 API/OpenAPI, 4 documentation routes.
- Alembic remains `20260827_0010`; there is no `0011`.
- Web and proxy code remain unchanged.
- Phase 9.7.D may resume against these two `/me/` contracts after independent D0 audit.
