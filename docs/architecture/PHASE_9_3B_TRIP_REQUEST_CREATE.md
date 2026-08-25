# Phase 9.3.B — Customer Trip-Request Creation

**Base commit:** `11aa4329f1ceea84ed3f177af5a351e439c89cc6` (the PR #28 merge of Phase 9.3.B0
onto `main`).

This slice delivers the first real **customer write journey**: a signed-in customer opens
`/portal/trip-requests/new`, picks real origin/destination airports, chooses a departure,
creates real passengers inline, creates exactly one **DRAFT** trip request, submits that same
DRAFT to **SUBMITTED**, and lands on the real detail page. It is a **web/client-only** change:
`apps/api/**` is byte-identical to the base, there is no migration, and no backend route,
schema, or route-policy change.

## Why 9.3.B0 is a prerequisite

The create contracts (`PassengerCreate`, `TripRequestCreate`) made `customer_id` **optional**
in 9.3.B0. That is what lets the browser create a passenger and a trip **without knowing or
sending the internal customer UUID**. The server derives the authoritative customer from the
authenticated principal plus the validated active organization
(`access.resolve_write_customer`). Building this journey on the pre-B0 base would have forced
the browser to send `customer_id` — the exact blocker 9.3.B0 resolved.

## Server-derived ownership (the browser never sends `customer_id`)

- `PassengerCreateRequest` and `TripRequestCreateRequest` (browser types) **do not contain
  `customer_id`** — it is absent by construction and asserted by unit tests, the E2E network
  capture, and a client-bundle grep.
- Ownership is derived server-side: authenticated `User` → validated active `Organization`
  (via `X-Organization-Id`, re-validated against the principal's memberships) →
  `organization.customer_id`. Omitting the id derives the owner; a mismatching id is still
  rejected/concealed (unchanged from 9.3.B0).

## Proxy routes added (closed allow-list)

Exact entries added to `PROXY_ALLOWLIST`:

| Path            | Methods | Purpose                                  |
| --------------- | ------- | ---------------------------------------- |
| `passengers`    | `POST`  | Create a real passenger (inline).        |
| `trip-requests` | `POST`  | Create the DRAFT trip request.           |
| `airports`      | `GET`   | Airport-picker source (collection read). |

One parameterized entry added to `PROXY_PATTERN_ALLOWLIST`:

| Pattern                          | Methods | Purpose                    |
| -------------------------------- | ------- | -------------------------- |
| `trip-requests/:uuid/submit`     | `POST`  | Submit the **same** DRAFT. |

All existing 9.3.A GET rules are unchanged. There is **no** `cancel`, `offers`, `booking`, or
`payment` route; no `trip-requests/*`, `passengers/*`, or `airports/*` wildcard; no prefix
matcher, generic passthrough, or arbitrary regex. `submit` is a three-segment pattern with a
literal trailing segment, so it can never widen the two-segment `{id}` GET. Encoded
separators, traversal, non-UUID ids, extra segments, and prefix-similar families are all
rejected (see `proxy.test.ts`).

## CSRF / active-organization context

Mutations flow through the same same-origin proxy and the existing typed client: the readable
CSRF cookie is attached as `X-CSRF-Token` on unsafe methods, and the validated active
organization is forwarded as `X-Organization-Id`. `Authorization` is never forwarded; the
upstream host is server-controlled; responses are `no-store`. None of this changed.

## Airport search

`GET /airports` takes **no query parameters** — it returns all active airports. The picker
therefore fetches the list once and filters **client-side** over name / city / IATA / ICAO
(`filterAirports`). The client method is named `listAirports` to reflect that there is no
server-side search contract. Selection always yields a real airport **UUID**; free text is
never submitted, and origin ≠ destination is validated client-side (and server-side).

## Inline passengers (there is no passenger roster endpoint)

There is no saved-passenger list endpoint, so the UI shows no fake roster and stores nothing
in `localStorage` / `sessionStorage`. The customer types passengers into the form; each is
created via `POST /passengers` (no `customer_id`), and the returned passenger UUIDs are held
in component memory and used as `TripRequestCreate.passenger_ids`. Multiple passengers are
supported. No passport / document / KYC fields are invented — only the exact backend fields.

## DRAFT creation, same-DRAFT submit, optimistic version

The creation state machine (`runCreation`) runs three idempotent phases against `progress`:

1. **create passengers** — only slots without an id (reuse the rest);
2. **create DRAFT** — only if none exists; assert the response `status === "DRAFT"`; retain
   `{ id, version }`;
3. **submit** — `POST /trip-requests/{id}/submit` with `{ expected_version }` = the DRAFT's
   returned version; assert `status === "SUBMITTED"`.

The submit uses the **exact same** trip id and the version the create returned. 409 conflicts
are surfaced as a refresh-and-retry message.

## Partial-failure semantics (no duplicates)

Because `progress` is retained in component memory across retries:

- **passengers created, trip failed** → retry reuses the created passenger ids and does not
  recreate them; the DRAFT is created once.
- **DRAFT created, submit failed** → retry submits the **same** DRAFT; it never creates a
  second trip and never recreates passengers.
- **partial passenger failure** → retry only creates the still-missing passenger.

A hard in-flight ref plus disabled CTA prevent a double-click from starting two runs. There is
**no fake rollback** and no delete attempt (the backend exposes no delete). **Limitation:** a
full page reload legitimately loses the in-memory retry state; this is documented and is **not**
worked around with browser storage.

## Safe error model

Raw backend `message` / `code` / body / ownership detail is never shown. Mapped messages:
passenger failure, trip-create failure, submit failure (with a distinct 409 "changed while it
was being submitted" message). No "you don't have access to this account" wording.

## SUBMITTED UX and navigation

On success the customer is announced "submitted" and navigated to
`/portal/trip-requests/{id}`, which shows `SUBMITTED`. No language implies a quote, operator
acceptance, aircraft reservation, booking, or payment. The list page gains a **New trip
request** CTA to `/portal/trip-requests/new` (shown only with a customer context); existing
list behaviour is unchanged.

## Out of scope (deferred)

No cancel, no offers, no offer selection, no booking, no payment, no operator UI, no dashboard
aggregation. Cancel and dashboard counts remain **9.3.C**. Grok is deferred to after 9.3.C.
The B1 email-production timing gate remains a separate concern.

## apps/api zero-diff / no migration

`apps/api/**` is byte-identical to the base. Route inventory remains **85 / 81 / 4**; Alembic
head remains **20260813_0009** (no `0010`, no migration). API suite: **500 passed**.

## Local E2E results (no email, no external providers)

A local, opt-in Playwright journey (`RUN_TRIP_CREATE_E2E=1`) ran against a disposable isolated
Postgres, a local API, and a local web server, with a seeded ACTIVE customer created via the
dev-only registration verification token (no email / Resend). It drove login → new form → real
seeded airports (Farnborough → Dublin) → passenger → create → submit → SUBMITTED detail →
list. DB assertions (scoped to the test customer): exactly 1 passenger owned by the derived
customer, exactly 1 trip request, 1 leg with the exact origin/destination airport ids, 1
trip-passenger link, status SUBMITTED, version progression 1 → 2, and 0 offers / bookings /
payments. The browser mutation payloads were captured and contained **no `customer_id`**.
Responsive checks passed at 320×568, 390×844, 768×1024, 1024×768, and 1440×900 with no
horizontal overflow, an in-viewport CTA, and no console/hydration errors.
