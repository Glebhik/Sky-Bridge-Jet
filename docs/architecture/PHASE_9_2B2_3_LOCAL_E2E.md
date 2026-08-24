# Phase 9.2.B2.3 — Local real customer-auth E2E (closure of Phase 9.2)

## Purpose & starting point

B2.3 is the **final local closure** of Phase 9.2 (customer authentication). It does not add
architecture: it **proves** the complete real customer journey end-to-end against a real
local runtime, with a **real verification email delivered through Resend**, and captures the
evidence. The auth implementation itself is unchanged.

- Starting commit (canonical `origin/main`): `52b17441ae3600939d1e1079703e67041e054d45`
  (merge of PR #25, Auth Visual Polish V1).
- **No production source change**: the E2E passed against the merged app as-is. This slice is
  therefore **documentation + an opt-in local harness only** — no backend, no route, no
  migration, no web behavior change, no dependency change.

## The journey that is proven

1. Open production `/register`.
2. Register a fresh account (email + password only; confirm is UI-only).
3. Backend creates a `PENDING_VERIFICATION` user (`email_verified_at` null) and a
   verification token row (stored **hashed** — see below).
4. Sky Bridge Jet sends **one real verification email** via Resend from
   `Sky Bridge Jet <no-reply@skybridgejet.disgroup.ie>`.
5. The email contains `http://localhost:3000/verify-email#token=<raw-token>`.
6. Open the link as a **fresh full-page load**.
7. The client reads the token from the URL fragment and **strips the fragment via
   `history.replaceState` BEFORE the verify POST** (parser `^#token=([A-Za-z0-9_-]+)$`).
8. Backend consumes the token (single-use) → user becomes `ACTIVE`, `email_verified_at` set.
9. Canonical personal provisioning runs (`provision_personal_customer`, ADR-044): exactly one
   `Customer` (`primary_email` = the user), one `CUSTOMER` `Organization` (`customer_id`), one
   active `CUSTOMER_OWNER` `OrganizationMembership` (`user_id`). No operator/admin role.
10. Follow the CTA to `/login?verified=1` (exact-flag success banner; no query reflection).
11. Log in → real server-side session (HttpOnly `sbj_session` cookie; JS-readable `sbj_csrf`
    double-submit cookie; no bearer/token in `localStorage`/`sessionStorage`).
12. Reach the **real `/portal`** (not `/demo`); `GET /auth/me` resolves the user and the
    canonical customer org context.
13. Log out → session revoked → `/auth/me` 401 → `/portal` redirects to `/login?next=%2Fportal`.

## Why the verification token is supplied manually (not read from the DB)

`email_verification_tokens` stores only a **`token_hash`** (SHA of the raw token) — the raw
token is never persisted and never logged (delivery logs only a safe category on failure).
The raw token exists **only in the delivered email**. Therefore a local E2E cannot
auto-recover the token from the database; the operator opens the real inbox and supplies the
`/verify-email#token=…` URL to the harness. This is a property of the security design, not a
gap: tokens are unrecoverable at rest.

## Opt-in harness (`tests/e2e/auth-journey.real.spec.ts`)

- **Never runs in CI** (CI runs no Playwright e2e) and is **double-gated**: it `skip`s unless
  **both** `RUN_REAL_AUTH_E2E=1` **and** `AUTH_EMAIL_ENABLED=true` are set.
- Reads the pasted verification URL from `SBJ_E2E_VERIFICATION_URL` (never committed).
- Exercises the security-critical **consumption** half — verify (fragment strip-before-POST) →
  login → real `/portal` → logout → lockout — asserting the fragment-strip, HttpOnly session,
  `/auth/me` customer context, and post-logout `401`. Registration is the documented preceding
  step (runbook §5); the spec deliberately does not re-register, because a second registration
  for the same pending account could rotate the token and invalidate the supplied link. The
  registration half (enumeration-safe ack, no auto-login) is covered by the web unit suite.
- Deterministic non-live coverage already lives in the suites: the fragment
  replaceState-before-POST ordering is pinned by `verify-email.test.tsx` (web, 106 passed) and
  the auth backend by `pytest` (API, 497 passed).

## Runbook (local only — never a deployed/public environment)

> `AUTH_EMAIL_ENABLED=true` is permitted **only** for this deliberate localhost run. The B1
> resend timing side-channel remains a production gate; do not enable email on any
> internet-facing deployment.

1. **Dedicated Postgres** (isolated; never touch `dis-postgres` on 5432):
   `DATABASE_PORT=5433 docker compose up -d db` → `alembic upgrade head` → `alembic check`.
2. **API config** comes from the git-ignored repo-root `.env` (the B1 email keys:
   `AUTH_EMAIL_ENABLED=true`, `RESEND_API_KEY`, `AUTH_EMAIL_FROM`, `WEB_PUBLIC_ORIGIN`) with DB
   component vars overridden to the dedicated port. The Resend key is never printed/committed.
3. **Start API**: `uvicorn sky_bridge_jet.main:app --host 127.0.0.1 --port 8000`
   (`APP_ENVIRONMENT=development`, `DATABASE_PORT=5433`).
4. **Start web**: `API_UPSTREAM_ORIGIN=http://127.0.0.1:8000 pnpm --dir apps/web dev`.
5. Register at `http://localhost:3000/register` with a fresh address you control.
6. Open the delivered email, copy the `/verify-email#token=…` link.
7. `SBJ_E2E_VERIFICATION_URL='<link>' RUN_REAL_AUTH_E2E=1 AUTH_EMAIL_ENABLED=true pnpm test:e2e`
   — or drive the steps manually and assert with `psql` against the dedicated DB.
8. **Cleanup**: stop web + API; `docker compose down -v` for the dedicated project only; leave
   `dis-postgres`, unrelated volumes, and `.env` untouched.

## Security invariants re-confirmed live

- Fragment token never in address bar after mount, DOM, rendered HTML, `localStorage`,
  `sessionStorage`, IndexedDB, cookies, query, or logs.
- Registration is enumeration-safe ("If everything is in order…"); no auto-login, no portal
  redirect, no token in the response or page.
- Verification token is single-use (replay returns `400`).
- Session cookie is HttpOnly (JS cannot read it; the session still authorizes `/auth/me`);
  cookie `Secure` is off only because the local run is plain http (on in production).
- `/auth/me` returns exactly one `CUSTOMER` / `CUSTOMER_OWNER` membership and customer-scoped
  permissions — no operator/admin/platform elevation.

## Boundaries (unchanged relative to base)

- `apps/api/**` byte-identical to base → API baseline **497 passed**, route inventory
  **85 / 81 / 4**, Alembic head **20260813_0009**, **no `0010`**, no migration.
- Web baseline **106 passed / 17 files**. No `/demo` or `/portal` business-UI change, no
  payment/booking/operator change, no dependency/lockfile change, no secrets, no Vercel change.
- CI never calls real Resend (`conftest.py` forces `AUTH_EMAIL_ENABLED=false`).

## Deferred

Phase 9.3 and profile/passenger work are **out of scope**. The B1 synchronous-resend timing
oracle remains the standing production gate and is intentionally **not** changed here.
