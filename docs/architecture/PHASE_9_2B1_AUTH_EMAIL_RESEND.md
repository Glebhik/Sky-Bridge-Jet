# Phase 9.2.B1 — Auth Email Delivery / Resend

## Purpose & starting point

Phase 9.2.B1 adds a **provider-neutral transactional auth-email seam** and a **Resend
adapter**, and wires verification-email delivery into the existing register and
verification-resend endpoints — **without** any Phase 9.2.B2 UI, **without** password-reset
email delivery, and **without** paid staging infrastructure.

- Canonical starting commit: `aa7db747f982cf16d84d49b455d2d91eca0a48f8` (post-merge
  Phase 9.2.A checkpoint).
- Externally verified sending domain (owner-configured): **`skybridgejet.disgroup.ie`**.
- Approved sender (server-controlled): **`Sky Bridge Jet <no-reply@skybridgejet.disgroup.ie>`**.
- A real manual Resend smoke has already succeeded (owner). No real key is present in this
  repository or worktree; implementation and CI run with auth email disabled.

## Provider-neutral architecture

Modeled on the existing Stripe seam (`core/stripe_gateway.py`). New `core/auth_email.py`:

- `AuthEmailSender` (`Protocol`) — `send_verification_email(message)`.
- `FakeAuthEmailSender` — deterministic, records every `VerificationEmail` in `.sent`; the
  **normal automated-test boundary** (no network, no credentials).
- `ResendAuthEmailSender` — the real adapter (see below).
- `build_auth_email_sender(settings)` — factory: fake when disabled, Resend when enabled;
  **fails closed** if enabled without a key (message never contains the key).
- `AuthEmailError` + `AuthEmailErrorCategory` — typed, provider-neutral failures.

Content is rendered by pure functions in `modules/iam/auth_email_content.py`
(`build_verification_url`, `build_verification_email`) — no template framework.

## Fake vs Resend adapter

- **Fake** is injected everywhere in automated tests; **no CI test calls Resend**.
- **Resend** performs a single `POST https://api.resend.com/emails` using the Python
  **standard library** (`urllib.request`) with an explicit 10s timeout — no `resend` SDK,
  no `httpx`/`requests`/`aiohttp` runtime dependency (so **no dependency/lockfile change**).
  It sends JSON (`from`/`to`/`subject`/`text`/`html`), sets `Authorization: Bearer` and
  `Content-Type` server-side, and validates a 2xx JSON response containing an `id`.

## Transaction / network boundary

The Resend call happens **only after the IAM transaction commits**. `AuthService.register`
and `resend_verification` return the raw token from inside `with session.begin()`, so the
caller receives it post-commit; the route handler then calls
`deliver_verification_email(...)` **outside** any transaction or `FOR UPDATE` lock. No
provider call ever runs inside `session.begin()` or a repository method.

## Verification URL (fragment design)

`{WEB_PUBLIC_ORIGIN}/verify-email#token=<raw-token>`. The token is URL-safe. This is
delivered **only by email**; the full URL is never logged. It is compatible with the
unchanged Phase 9.2.A API — B2 will read the fragment client-side, strip it via
`history.replaceState`, and POST `{token}` through the same-origin proxy to the existing
`POST /auth/verify-email`. No API change and no new route.

## Failure semantics

A durable account/token operation is **never rolled back** because Resend is unavailable.
`deliver_verification_email` catches `AuthEmailError` and records a safe structured log
(`auth_email_delivery_failed` with only `operation` + `error_type`; the JSON log formatter
whitelists fields, so recipient/token/URL/header/key can never be logged). Register keeps
its normal contract; resend keeps its enumeration-safe acknowledgement. Provider error
categories: `PROVIDER_UNAVAILABLE` (network/timeout/5xx), `PROVIDER_AUTHENTICATION_ERROR`
(401/403), `PROVIDER_RATE_LIMITED` (429), `PROVIDER_INVALID_REQUEST` (other 4xx),
`PROVIDER_INVALID_RESPONSE` (malformed success), `PROVIDER_CONFIGURATION_ERROR`.

## Enumeration safety

The resend HTTP response is byte-identical (uniform message, 200) whether the email is
unknown, malformed, ineligible, or eligible, and whether the provider succeeds or fails; a
send is attempted only for an eligible pending account, and any failure is swallowed. The
5/60-per-IP resend limit and the 9.2.A token-invalidation/concurrency guarantees are
unchanged. (Note: delivery is synchronous, so provider latency is observable to a caller —
a minor timing side-channel acceptable for the local B1 baseline; production hardening
would move sending off the request path.)

## Settings & local secret handling

New server-only settings (never `NEXT_PUBLIC_*`): `AUTH_EMAIL_ENABLED` (default `false`),
`RESEND_API_KEY` (default empty), `AUTH_EMAIL_FROM` (server-controlled default sender),
`WEB_PUBLIC_ORIGIN` (default `http://localhost:3000`). A settings validator:

- normalizes `WEB_PUBLIC_ORIGIN` to a bare absolute http(s) origin and rejects
  credentials/path/query/fragment;
- **fails closed** if `AUTH_EMAIL_ENABLED` is set without `RESEND_API_KEY` (error never
  contains the key);
- requires an **https** origin in production when email is enabled.

Tests/CI boot with email disabled and no key. The repository-root `.env` remains
git-ignored; **only `.env.example`** carries safe placeholders (no real key). The owner
owns and configures the local `.env`. No real key exists in Git, tests, docs, or web code.

## Web bundle secret hardening

`scan-client-bundle.mjs` now also fails if a client asset contains `RESEND_API_KEY`, the
runtime `process.env.RESEND_API_KEY` value, or a `re_…` key pattern.

## Manual smoke (opt-in, never in CI)

`apps/api/scripts/auth_email_smoke.py` sends **one real** verification email using the
configured adapter. It is not a pytest test, requires `SMOKE_SEND=1` **and**
`AUTH_EMAIL_ENABLED=true`, never prints the key, uses a clearly fake token (creates/
verifies no account), and states that it consumes Resend quota. The owner runs it manually
after independent audit; it was **not** executed during implementation (the key is
intentionally unavailable).

## Migration / route inventory

**No migration** (delivery is stateless; no provider message id persisted). **No new API
route.** Route inventory remains **85 normalized / 81 OpenAPI / 4 docs**; Alembic head
remains `20260813_0009` with no drift.

## Scope

Implemented (B1): the seam, fake + Resend adapter, settings + validation, verification
email content, register/resend wiring, tests, bundle-scan hardening, and the opt-in local
smoke.

Deferred to **B2**: `/register`, `/verify-email`, resend UX, Midnight Aviation production
auth styling, and the browser fragment-token consumer. **Password-reset email delivery is
intentionally not implemented in B1**; the password-reset endpoints are unchanged. No
profile/passengers; no Phase 9.3.
