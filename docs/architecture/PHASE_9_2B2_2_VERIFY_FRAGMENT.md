# Phase 9.2.B2.2 — Verify Email Fragment Consumer + Verification UX

## Purpose & starting point

Implements the real browser verification-consumption flow: the emailed link
`/verify-email#token=<raw-token>` is opened, the client reads the token from the URL
fragment, immediately strips it from the URL/history, verifies it through the existing
same-origin proxy, and shows an explicit result with a "Continue to sign in" CTA. Web-only:
no backend, proxy, typed-client, migration, or route-policy change.

- Starting commit: `844bfbf4be508cf0dbba27813007e6f0e9f2bdd3` (post-merge Phase 9.2.B2.1).
- Deferred: **B2.3** (local real registration→verify→login E2E). Not in this slice: password
  reset delivery/UI, profile/passengers, and anything beyond verification UX.

## Fragment rationale

The raw verification token travels in the URL **fragment** (`#token=…`), never a query
string, because a fragment is not sent to the server in the HTTP request. Therefore the
Next.js server/RSC never receives the token: `/verify-email` is a thin **server shell** that
renders a **client** verifier, and there is no `searchParams` token on this route.

## Exact fragment-consumption sequence (client, on mount)

1. Read the token strictly from `window.location.hash`.
2. **Immediately** strip the fragment from the visible URL/history with
   `window.history.replaceState(null, "", pathname + search)` — **before any network call**.
3. POST the token via `portalApi.verifyEmail(token)` (same-origin proxy).
4. Discard the token from memory as soon as it is no longer needed.

The token is held only in a React `ref` (ephemeral memory) to allow a retry after a
transient failure. It is never rendered, logged, placed in error copy, or written to
`localStorage`/`sessionStorage`/`IndexedDB`/cookies/query. The fragment is never restored.

**replaceState-before-POST is a hard requirement** and is proven by an automated test that
records call order: `replaceState` fires first (with a URL containing no `#`), then
`verifyEmail`. The mount-time effect performs the read/strip on a fresh page load (the real
email-link flow), verified both by unit tests and a live hard-reload runtime check.

## Token parsing (conservative)

`readTokenFromHash` accepts **only** `^#token=([A-Za-z0-9_-]+)$`. B1 tokens are
`secrets.token_urlsafe` (base64url: `A–Z a–z 0–9 _ -`, no `+ / = %`), so this exact-match
regex preserves the token bytes with **no decoding/mutation** and rejects: no hash, empty
token, a different/extra fragment key, malformed characters, and multiple `token=` values.
No permissive multi-key parser is used.

## State machine

Only states the backend can actually distinguish (verify-email returns 200 on success and
`400 invalid_token` for every invalid/expired/used/already-verified case):

- `verifying` — spinner, `aria-live` region, no token rendered.
- `verified` — "Your email is verified" + **Continue to sign in → `/login?verified=1`**
  (no auto-login, no silent redirect, no user/org/role details).
- `invalid_or_expired` (HTTP 400) — "This verification link can't be used" + a resend form +
  Back to sign in. (Not labelled "expired" vs "used" because the backend does not
  distinguish.)
- `missing_token` — "Verification link unavailable" + resend form + Back to sign in.
- `network_error` — transient network/server failure; "Retry verification" reuses the token
  held in ephemeral memory (the fragment is never restored to the URL). If the token is not
  available, retry is inert.

## Resend email-entry UX

Because the token does not safely expose the account email client-side, `ResendVerificationForm`
asks the user for their email explicitly and calls `portalApi.resendVerification(email)`. The
acknowledgement is uniform and enumeration-safe (never reveals account existence/status/
provider outcome/token); `429` and transient errors surface neutral messages independent of
account existence; the copy never branches on network timing; double-submit is prevented; and
nothing is persisted client-side.

## Login verified banner

`/login?verified=1` shows a success banner "Your email is verified. Sign in to continue."
The flag is treated as a **fixed boolean**: only the exact value `1` renders the banner, no
query content is ever reflected into the page, and `verified=<anything else>` renders
nothing. It coexists with the existing sanitized `next` (`/login?next=/portal&verified=1`);
`sanitizeReturnPath`, the authenticated redirect, session/CSRF, and the register link are all
unchanged.

## Isolation, analytics, visuals

Reuses the B2.1 `AuthShell` (Midnight Aviation, text wordmark only, no invented emblem, no
non-approved marketing phrase). No `/demo` import, no `DEMO_PORTAL_ENABLED`. Verification-state
styles are scoped under `.sbj-auth`. There are **no third-party analytics/telemetry/scripts**
anywhere in the app, so the token-consumption page cannot leak the token to third-party code;
none are added.

## API / route / migration

Web-only. `apps/api` is byte-identical to base: **API 497 passed**, route inventory
**85 / 81 / 4**, Alembic head **20260813_0009** (no migration, no new route). `/verify-email`
is a static shell (`○`); `/register` and `/login` remain dynamic.

## Known production timing gate (unchanged)

The B1 resend timing side-channel remains a production gate; B2.2 neither fixes nor surfaces
it (uniform, timing-independent resend UI). Do not enable `AUTH_EMAIL_ENABLED` in an
internet-facing environment until verification delivery is moved off the request path or made
timing-independent. **B2.3** owns the local real E2E and is deferred.
