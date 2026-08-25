# Phase 9.3.A — Portal trip-request reads

## Starting point

- Canonical base (`origin/main`): `23b09cc012ffd41fa17c28565dc8d212f48c5a5d` (Phase 9.2 complete).
- **Phase 9.3 goal:** turn the authenticated customer portal from a protected read-model
  preview into a usable trip-request self-service core — without crossing into operator
  workflows, offer comparison, booking creation, or payments.
- **9.3.A purpose (this slice):** make the customer's own trip requests visible in the portal
  by wiring the already-existing customer-authorized read backend, and extend the same-origin
  proxy from exact-path matching to a **closed, parameterized** matcher for the specific
  customer resource-by-id GET routes those pages need. Read-only: no create/submit/cancel.

## Existing backend reused (no API change)

Every route below already exists on `main` and is already authorized for the customer (Phase
9.0.A-1 `customer/platform` and 9.0.B safe read models). 9.3.A adds **no** API route, schema,
migration, or backend behaviour — `apps/api/**` is byte-identical to base.

- `GET /me/trip-requests` — the customer's own trip requests (safe projection, org-scoped).
- `GET /trip-requests/{id}` — one owned trip request (same `TripRequestResponse` shape).
- `GET /airports/{id}` — **public** airport lookup, used only to label a leg's endpoints.

## Closed proxy-pattern architecture

The same-origin proxy stays a **closed allow-list**. It is now two-tier:

1. `PROXY_ALLOWLIST` — exact joined-path entries (unchanged; all existing routes still match
   exactly as before).
2. `PROXY_PATTERN_ALLOWLIST` — a tiny, explicit list of parameterized entries, each a fixed
   sequence of literal segments plus a `":uuid"` placeholder:
   - `trip-requests/:uuid` → `GET`
   - `airports/:uuid` → `GET`

Matching (`validateProxyRequest`) tries the exact map first, then the patterns. A pattern
matches **only** when the segment count is identical, every literal segment is equal, and each
`:uuid` segment is a canonical UUID. It is **not** prefix matching, a wildcard, a regex
catch-all, or a passthrough.

### Security rationale

- Incoming segments are already rejected by `isUnsafeSegment` if empty, `.`/`..`, containing a
  slash/backslash, or **any** percent-encoding — so encoded traversal, encoded slashes, and
  dot-segments never reach the matcher.
- The `:uuid` bind means opaque/garbage ids and extra path segments (e.g.
  `trip-requests/{id}/submit`) are `404` — a mutation sub-route can never be reached through a
  read pattern. Wrong methods are `405`; only `GET` is permitted here.
- The upstream host stays server-controlled; the `Authorization` header is never forwarded;
  cookies/CSRF/`X-Organization-Id` forwarding and `Cache-Control: no-store` are unchanged. The
  concrete (already-validated) path is what forwards upstream.
- Unit tests assert: allowed GET on each family; `405` on POST/PUT/PATCH/DELETE; `404` on the
  collection path, extra segments, mutation sub-routes, non-UUID ids, encoded separators, and
  other/prefix-similar `{id}` families; and that the exact allow-list still behaves as before.

## Exact customer GET routes exposed

`trip-requests/{id}` and `airports/{id}` (both GET) — nothing else. No collection creation, no
sub-routes, no other resource families.

## Trip-request list / detail UI

- `/portal/trip-requests` — a real org-scoped read of `/me/trip-requests` with honest
  loading / empty / error (forbidden vs generic) / list states; each row shows the real status,
  a leg summary, passenger count, and links to the detail. No fabricated pricing/aircraft/operator.
- `/portal/trip-requests/[id]` — a **read-only** detail: status, itinerary (legs with airports
  resolved best-effort via `/airports/{id}`, falling back to the leg timezone), passengers, and
  requirement notes. Handles loading / not-found (404) / forbidden / error without leaking
  internal error bodies. **No submit / cancel / edit / offer-select / book / pay controls.**
- Navigation gains a **Trip requests** destination (active on the list and nested detail); the
  dashboard gains a trivial navigation-only card. No aggregation/counts (that is 9.3.C).

## Boundaries

- **No mutations** — reads only. **No API change, no new route, no migration** (`apps/api`
  byte-identical; route inventory **85 / 81 / 4**; Alembic head **20260813_0009**, no `0010`).
- **No payment/offers/booking changes.** The unused `listPayments` client method is left
  deferred — 9.3.A stays focused on trip-request reads; a payment surface belongs to a later phase.
- **9.3.B** (passenger + trip-request creation/submit) and **9.3.C** (cancel + dashboard
  aggregation) are deferred.
- **Grok** visual polish is deferred until the functional 9.3 slices are complete and audited;
  it is not invoked here. Functional real UI first.
- The **B1 production email timing gate** remains a separate, parallel production-hardening
  item — untouched and unrelated to this slice.
