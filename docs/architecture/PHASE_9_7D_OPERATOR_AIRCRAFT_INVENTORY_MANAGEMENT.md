# Phase 9.7.D — Operator aircraft inventory and basic management

Canonical base: `b4e757724cd2ec3097782d752d2ae10ea250493c`. This Web phase depends on the bounded D0 aircraft collection/detail/create contracts and the A1 operator-safe aircraft discovery semantics already present on that base. It introduces no API production change or migration.

## Scope and authority

The operator Web workspace exposes a factual inventory, one aircraft detail, and aircraft creation. The existing D0 API remains authoritative. All five operator roles can read; only `OPERATOR_ADMIN` is given a create control. The browser never supplies an operator identity, and the API derives active authority from the authenticated principal plus the validated `X-Organization-Id` membership context.

There is deliberately no edit, status transition, delete, maintenance, scheduling, crew, document, certification, payment, refund, or admin authority. `eligible` is displayed only as “Eligible for marketplace offers” or “Not currently eligible.” It is not a certification or airworthiness claim, and ownership, status, and compliance remain subject to server revalidation when an offer is submitted.

## Closed proxy and typed browser contract

The same-origin proxy adds exactly:

- `GET /api/proxy/me/operator-aircraft`
- `POST /api/proxy/me/operator-aircraft`
- `GET /api/proxy/me/operator-aircraft/{canonical_uuid}`

The detail matcher accepts exactly one canonical UUID segment. Other methods and extensions fail closed. The typed client always uses `credentials: same-origin`, `cache: no-store`, the organization header, an `AbortSignal` for reads, and the existing double-submit CSRF header for creation. It has no upstream host, bearer token, wildcard path, or direct API access.

Browser-visible aircraft values are restricted to `id`, `registration`, `manufacturer`, `model`, `category`, `passenger_capacity`, `status`, and `eligible`. Creation sends only `registration`, `manufacturer`, `model`, `category`, and `passenger_capacity`.

## Multi-organization and concurrency safety

Multi-organization sessions make no aircraft request until the user explicitly chooses an operator organization. Reads use an abort controller and a monotonic organization epoch. Organization changes abort the old read, clear scoped data synchronously, and reject late A→B→A results.

Creation acquires an immutable token stored under the active organization-and-epoch key before the first await. A synchronous duplicate guard permits one POST within that exact scope. Returning to an organization under a newer epoch creates an independent key, so a pending old attempt does not make the new form an enabled no-op. A late response can update the UI only when its organization and epoch are still current, and an old `finally` may delete only the token at its own key when identity still matches. There is no automatic retry, optimistic success, polling, storage, websocket, or SSE.

## UI behavior

`/operator/aircraft` provides loading, empty, isolated error, manual refresh, inventory cards, and an admin-only create form. `/operator/aircraft/{aircraft_id}` performs one explicit detail read and provides loading, 404, error, and future-safe factual value handling. Cards link explicitly to detail.

Inventory pagination is user-driven and bounded to 20 rows per server request. Previous and Next issue exactly one collection GET with the corresponding offset; the browser never crawls or aggregates all pages and never claims a total page or fleet count that the API does not provide. A full 20-row page factually enables Next. If that continuation is empty, the UI retains the last non-empty page and disables Next. Organization changes reset offset to zero, while manual refresh preserves the current offset. Read request identity plus the organization epoch rejects late page responses.

Successful creation uses the POST only as command authority, clears the form, resets pagination to the first page, and performs exactly one authoritative collection refresh. It does not insert the POST response and refresh simultaneously, so no duplicate can be produced. Collection rendering never performs row-level detail or compliance requests and therefore remains NO N+1.

The responsive grid collapses naturally through 320, 390, 768, 1024, and 1440 pixel viewports. Native labels, headings, links, buttons, status alerts, and busy/loading semantics provide the accessibility baseline.

## Deferred work

Aircraft editing, activation/deactivation, expanded aircraft management, maintenance, scheduling, crew, manifests, document/evidence handling, and compliance decisions are intentionally deferred.
