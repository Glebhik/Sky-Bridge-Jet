# Customer Portal demonstration preview

## Purpose and non-scope

`/demo` is a public, read-only inspection surface for the Customer Portal shell on mobile,
tablet, and desktop. It is explicitly a **Customer Portal Demonstration** using synthetic
fixtures. It is not Phase 9.1.C, does not implement booking, offer, payment, checkout,
profile, or account workflows, and is not evidence that any such workflow exists.

## Strict separation from `/portal`

The authenticated `/portal` boundary is unchanged: the request proxy still matches only
`/portal/:path*`, and the portal layout still validates the backend session before rendering
protected content. The demo has its own layout, shell, navigation, fixtures, and server-only
flag. It does not import the session or organization providers, the typed API client, proxy,
authentication, or authorization modules. Production portal/security modules never import
demo fixtures. Demo state is presentation state only and is never authorization state.

The demo makes no API or database request, creates no session, reads or writes no auth or
CSRF cookie, performs no mutation, and stores no token or personal data in browser storage.
The only demo client state is whether its mobile navigation menu is open.

## Fail-closed server-only feature flag

`DEMO_PORTAL_ENABLED` is read only by a module guarded with `server-only`. Its safe default
is absent/`false`; only the exact string `true` enables rendering. Otherwise every route
under `/demo` resolves through `notFound()` to HTTP 404. The decision accepts no request
input, so headers, query parameters, cookies, form fields, and request bodies cannot enable
the demo. The variable must never be renamed to or mirrored in a `NEXT_PUBLIC_*` variable.

## Vercel configuration

To enable a deliberate preview, add this **server-side Environment Variable** to the exact
Vercel project and intended environment (normally Preview), then create a new deployment:

```text
DEMO_PORTAL_ENABLED=true
```

Do not expose it as `NEXT_PUBLIC_DEMO_PORTAL_ENABLED`. This repository task does not modify
the Vercel account or deploy anything.

To disable the demo immediately, set `DEMO_PORTAL_ENABLED=false` (or remove it) for the
affected Vercel environment and redeploy. The route then fails closed with 404.

## Search-indexing policy

The demonstration is **never** meant for public search indexing, even when the feature flag
is deliberately enabled. The `/demo` layout exports Next.js `robots` metadata
(`index: false`, `follow: false`, plus the Googlebot equivalent), so every enabled demo
route emits `<meta name="robots" content="noindex, nofollow">` (and the matching
`googlebot` tag). Because the directive lives only on the `/demo` layout subtree, the public
landing (`/`), `/login`, and the authenticated `/portal` are unaffected and carry no such
directive. When the flag is off the routes are 404 and are not indexable regardless.

## Synthetic-data policy

All demonstration objects live in `apps/web/src/lib/demo/fixtures.ts`. Identifiers use the
`DEMO-*` namespace and names are limited to `Demo Customer` and `Demo Travel Office`.
Fixtures include presentation-only trips, booking statuses, and customer-safe comparison
fields. They contain no real name, email, phone, payment data, operator data, aircraft
registration, database identifier, provider reference, internal amount, platform fee,
allocation, settlement eligibility, internal note, or idempotency key.

Every demo page inherits this visible warning:

> Demonstration Preview — synthetic data only. No booking or transaction is created.

Buttons that could imply an offer action are disabled and labelled as demo-only.

## Route inventory

- `/demo` — synthetic dashboard summary.
- `/demo/bookings` — synthetic presentation cards; no lifecycle logic.
- `/demo/offers` — synthetic read-only comparison; no selection or commercial action.
- `/demo/account` — synthetic account presentation; no account action.

This preview is a safe technical surface for later independent styling. It does not approve
a permanent slogan or brand treatment and does not start Grok Build or Phase 9.1.C.
