# Phase 9.1.B — Customer Portal Foundation and Responsive Application Shell

## Purpose

Phase 9.1.B is the first visible, production-shaped foundation of the Customer Portal:
same-origin API access, a typed client, backend-driven session/auth state, a safe login
redirect, a protected route boundary, active customer-organization context, and a
responsive application shell with reusable UI primitives. It is **infrastructure and shell
only** — it deliberately does **not** implement the booking, offer, payment, profile, or
checkout workflows. It is a frontend-only change: no API source, no route-policy
classification, no permission, and no database migration were touched (the API inventory
remains 84 normalized / 80 OpenAPI / 4 docs, 459 tests green).

## Same-origin proxy boundary (`src/lib/server/config.ts`, `src/lib/server/proxy.ts`, `src/app/api/proxy/[...path]/route.ts`)

The browser communicates **only** with the web application's own origin. All API calls go
to `/api/proxy/<path>`, which a Node route handler forwards to the upstream API. Security
properties:

- **Trusted host only.** The upstream origin comes from a server-only `API_UPSTREAM_ORIGIN`
  (never a `NEXT_PUBLIC_*` value, never a request header). `import "server-only"` prevents a
  client bundle from importing the proxy configuration.
- **Closed path allow-list.** Only the explicit `{ path: methods }` entries in
  `PROXY_ALLOWLIST` are reachable (session, login/logout, explicit recovery, and the
  customer "my" reads). Anything else is `404`; a wrong method is `405`. There is no
  arbitrary URL forwarding and no open-proxy behaviour.
- **SSRF / traversal safe.** Path segments are rejected if empty, `.`/`..`, or containing
  slashes/backslashes/percent-encoding; the upstream URL is built from the trusted origin +
  fixed `/api/v1` prefix + the validated path, so neither the host nor a traversal can come
  from the request.
- **Faithful forwarding.** Method, query string, and request body are preserved. Only a
  closed set of request headers is forwarded (`cookie`, `x-csrf-token`, `x-organization-id`,
  `content-type`, `accept`) — never the browser `host`, `authorization`, or arbitrary
  headers. Upstream `Set-Cookie` values (session + CSRF) are relayed back, and every proxied
  response is `Cache-Control: no-store` so authenticated responses are never cached.
- **Honest failures.** Upstream status codes (401/403/404/409/422/429/5xx) are preserved
  verbatim — never collapsed to a generic 200. An unreachable upstream yields a controlled
  typed `502 upstream_unavailable`. Cookies, tokens, authorization headers, and bodies are
  never logged.

## Browser vs. server trust boundary

Server-only modules (`lib/server/*`, `lib/session/server.ts`) hold the upstream origin and
perform server→server calls; they are never bundled to the browser. The browser receives
only customer-safe data through the proxy and holds no API host, no secrets, and no
authorization state. The typed client (`lib/api/client.ts`) uses `credentials:
"same-origin"` and attaches the readable CSRF cookie as `X-Csrf-Token` on mutations; it
exposes only customer-appropriate types (Phase 9.1.A customer-safe schemas) — no
operator/platform/internal models.

## Session state model (`lib/session/model.ts`, `lib/session/server.ts`, `components/session/session-context.tsx`)

The session is a reflection of the backend session, never an authorization decision. The
server bootstrap calls `/auth/me` and yields one of: `authenticated` (with derived CUSTOMER
organizations), `unauthenticated` (a backend 401), or `error` (transient network/5xx). The
client `SessionProvider` is seeded with the server snapshot (no protected-data flash) and
can re-validate; a 401 on refresh becomes `unauthenticated`, while a transient failure keeps
the last snapshot — a network blip never silently logs the user out. "Authenticated but
without a usable customer context" is expressed as `authenticated` with zero customer
organizations. Nothing sensitive is persisted in browser storage.

## Safe redirect policy (`lib/auth/redirect.ts`, `src/proxy.ts`)

A request `proxy` (Next.js's request-middleware convention) guards `/portal/*`: if the
session cookie is absent it redirects to `/login?next=<sanitized path>`; otherwise it lets
the request through to the authoritative layout check and forwards the requested path. The
return path is always sanitized to a **same-origin absolute path** — absolute URLs,
protocol-relative `//host`, backslashes, control characters (CR/LF), and the login page
itself are rejected and fall back to `/portal`. Cookie presence in the proxy is only a
redirect heuristic; the backend remains the sole authority.

## Protected-route model (`src/proxy.ts`, `app/portal/layout.tsx`)

`/portal/*` is protected in two layers: the request proxy (cheap cookie redirect + return
path) and the server layout, which calls `getServerSession()` and — before rendering any
protected content — redirects unauthenticated users to login (with the safe return path),
shows a recoverable error on a transient failure, or renders the shell for an authenticated
session. Because the decision is made server-side, protected customer data never flashes for
an unauthenticated visitor.

## Active-organization rules (`lib/org/model.ts`, `components/session/org-context.tsx`)

The selectable organizations come only from the authenticated backend session's CUSTOMER
memberships (never OPERATOR/PLATFORM). A stored preference is validated against that list on
every render and **discarded if stale/unauthorized**; a single org auto-resolves, several
offer a controlled selector, and none yields the "no usable customer context" state.
Switching changes `activeOrganizationId`, which organization-scoped consumers key their data
on, so stale org-scoped data is invalidated on switch and re-scoped via the validated
`X-Organization-Id` header (which the API still re-checks). Account recovery is only ever
triggered by an explicit user action on the Account page — never automatically.

## Responsive shell and components

The shell (`components/shell/*`) provides a sticky header (brand, desktop nav bar / toggled
mobile panel, active-organization presentation/selector, user menu), a skip link, a labelled
`nav` with `aria-current` on the active item, an `aria-expanded`/`aria-controls` mobile
toggle, visible focus states, and a main content landmark — responsive across mobile,
tablet, and desktop. Foundational UI primitives (`components/ui/primitives.tsx`) cover
Button, Card, Badge, Alert, Field, LoadingState, EmptyState, PageHeading, and Container,
styled with the existing CSS-token system (no UI library added; only `server-only` was
added as a dependency, for the trust boundary). The dashboard, bookings, offers, and account
pages are honest placeholders: bookings performs a real org-scoped `/me/bookings` read with
loading/empty/error/list states; offers and profile editing are explicit "coming soon"
empty states with no fabricated data.

## Explicit exclusions (later phases)

Not in this phase: booking/offer-comparison/payment/checkout/profile workflows; passenger,
trip, and card collection; live payment provider; registration/verification/password-reset
UI; and any change to API authorization, permissions, recovery behaviour, or route-policy
classification. Booking, offer, payment, and checkout workflows are **not** complete.

## Deferred backend item

The Phase 9.1.A architecture note listed "disable `/docs` `/redoc` `/openapi.json` in
production" under the 9.1.B umbrella. This command scopes 9.1.B to the frontend shell and
forbids route-policy classification changes, so that backend docs-hardening is intentionally
**deferred** to a separate backend change rather than included here.
