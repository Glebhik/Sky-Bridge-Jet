# Phase 9.2.B2.1 — Register Flow + Production Auth Visual Shell

## Purpose & starting point

The first real browser-based customer registration path, plus a production "Midnight
Aviation" auth visual shell shared by `/register` and `/login`. Web-only: no backend,
proxy, typed-client, migration, or route-policy change.

- Starting commit: `fee7b7945bc2c9e0692e06956d61de3977f25b38` (post-merge Phase 9.2.B1).
- Slice scope: **B2.1**. Deferred: **B2.2** (`/verify-email` fragment consumer) and **B2.3**
  (local real E2E hardening).

## Register contract used

`portalApi.register(email, password)` → same-origin proxy → `POST /api/v1/auth/register`
(unchanged). Request carries **only** `{email, password}`; confirm-password is UI-only.
Backend rules mirrored client-side for convenience (authoritative on the server): **12–200
characters, at least one upper- and one lower-case letter**. No display name / phone /
profile / passenger / organization / role / payment fields are collected (those are later
phases).

## No dev verification_token

`RegistrationResponse.verification_token` (dev-only; `null` in production) is **never read
or rendered**. The form awaits `portalApi.register(...)` and discards the result; the UI
behaves as though the field does not exist. A test asserts the token string never reaches
the DOM. Real email (Phase 9.2.B1) remains the canonical verification mechanism.

## Success-state semantics

On success the form stays on `/register` and swaps to a "Check your email" panel: *"If
everything is in order, we've sent a verification link to {email}. The link expires in 24
hours."* It does **not** auto-login, does **not** redirect to `/portal`, and does **not**
claim guaranteed delivery (B1 swallows provider failures). Actions: **Resend verification
email** and **Back to sign in**.

## Resend — enumeration-safe UX

`portalApi.resendVerification(email)` uses the already-entered email. The acknowledgement
is uniform ("If the account requires verification, we've sent new instructions.") and never
reveals account existence/eligibility, status, provider result, or a token. A `429` shows a
neutral "please wait" message and other failures a neutral retry message — both independent
of account existence. Copy never branches on network timing, so the **B1 timing
side-channel is not surfaced or worsened by the UI**. The resend button is disabled while a
request is in flight (no overlapping submits).

## Error mapping (no raw backend text)

| Condition | UI copy |
|---|---|
| `conflict` (409) | "An account with this email may already exist. Try signing in." |
| `rate_limited` (429) | "Too many registration attempts. Please wait and try again." |
| `client` (400/422) | "Check your email and password and try again." |
| password mismatch (client) | "Passwords do not match." |
| network/server | "We couldn't create your account right now. Please try again." |

No internal codes, stack traces, org data, user ids, provider errors, or Resend details
are shown.

## Login integration

`/login` gains a **"New to Sky Bridge Jet? Create an account"** link to `/register` and is
wrapped in the shared `AuthShell`. Login behaviour is unchanged — `getServerSession`,
authenticated redirect, `sanitizeReturnPath`, `portalApi.login`, HttpOnly-cookie authority,
CSRF, safe-`next`, and organization context are all untouched. No `?verified=1` behaviour
is added (verification success belongs to B2.2).

## Auth visual shell & brand

`components/auth/AuthShell.tsx` is a presentational shell (Midnight Aviation: midnight/navy
ground, restrained champagne accent, premium editorial serif headings, mobile-first). It
imports nothing from `/demo`, needs no `DEMO_PORTAL_ENABLED`, and all styling is scoped under
`.sbj-auth` in `globals.css` (including scoped overrides of the shared primitives), so
`/portal` and `/demo` are unaffected. **No canonical production emblem asset exists → text
wordmark "Sky Bridge Jet" only**; a reserved mark slot is hidden (`display:none`). No traced
screenshot, no recreated wings, no V1 wave glyph, no invented plane/globe/crown.

## Metadata / robots

`/register` and `/login` each export route-specific metadata with **`robots: index:false,
follow:false`** (and Googlebot equivalents) for this local-first phase, plus factual titles
("Sky Bridge Jet — Create Account" / "— Sign In"). The route-specific `description`
supersedes the inherited root description on these pages, so the non-approved phrase
"Premium Private Aviation Marketplace" never appears on the auth surfaces (verified at
runtime). The root metadata is left for a separate branding task.

## Accessibility & responsive

Semantic `<form>`, label-bound `Field` inputs, `aria-describedby` for the password hint,
`role=alert`/`status` via `Alert`, visible champagne focus ring, disabled/busy button
states, ≥44px touch targets, correct `type=email`/`inputMode=email`, `autocomplete`
`email`/`new-password`, reduced-motion support. Verified at 320/390/768/1024/1440 with **no
horizontal overflow**, no console/hydration errors, and no broken resources.

## Scope, migration & route impact

New web routes only (`/register`; `/login` restyled). **No API operation added** — route
inventory remains **85 / 81 / 4**; **no migration** (Alembic head `20260813_0009`). No
change to `/demo`, `/portal` business UI, profile/passengers, trip requests, offers,
bookings, payments, Stripe, operator/admin, API auth logic, `AuthEmailSender`, the Resend
adapter, route policy, manifests, lockfiles, CI, Docker, or Vercel.

## Known production timing gate (unchanged)

The B1 MINOR stands: synchronous verification-resend delivery is a timing side-channel when
`AUTH_EMAIL_ENABLED=true`. B2.1 neither fixes nor worsens it (uniform, timing-independent
UI). **Do not enable `AUTH_EMAIL_ENABLED` in an internet-facing environment** until delivery
is moved off the request path or made timing-independent. B2.1 runs with auth email disabled
by default; a deliberate local E2E (B2.3) may enable it on `localhost` only.

## Deferred

- **B2.2** — `/verify-email` fragment consumer (`#token=…` read + `history.replaceState`
  strip + verify POST + state machine) and standalone resend UX.
- **B2.3** — local real E2E hardening.
