# Phase 9.2.A — Auth Contract & Backend Readiness

## Purpose

Phase 9.2.A prepares the existing identity backend and the web trust boundary for a
complete customer account-entry experience (registration → verification → login →
recovery), **without** building any of the Phase 9.2.B UI and **without** integrating a
real transactional email provider. It closes four readiness gaps found in the accepted
baseline audit and extends the browser-safe contract surface so 9.2.B can build screens
against stable, typed endpoints.

## Starting checkpoint

- Canonical `main`: `951da50066ab55e1e741413d630900b47ebbc747` (merge of PR #20).
- Branch: `feature/phase-9-2a-auth-readiness`.
- Reproduced baseline before any change: API **459 passed**, Web **76 passed / 14 files**,
  route inventory **84 / 80 / 4**, Alembic head **`20260813_0009`**, no drift.

## What changed

### 1. Registration rate limiting (abuse protection)

`POST /api/v1/auth/register` performs Argon2 hashing and a persistent write for an
anonymous caller but previously had no limiter. It now enforces a conservative per-IP
fixed-window floor (`_register_limiter`, **5 attempts / 60 s per client IP**) **before**
the hash/persist work. The key is the client IP only (never the email), so a denial
reveals nothing about whether any account exists, and the existing safe `409`
duplicate-email contract is unchanged for legitimate requests. Denials use the existing
`RateLimitedError` → `429` envelope (`{"error":{"code":"rate_limited", ...}}`).

This in-process limiter is a **Phase 9.2 application-level baseline**, not a distributed
anti-abuse platform; production continues to front these endpoints with a
reverse-proxy/WAF. No Redis or other infrastructure dependency is introduced.

### 2. Verification resend

New public endpoint **`POST /api/v1/auth/verification/resend`** (request body: `email`
only) lets a customer recover from a lost or expired verification link. It is
**enumeration-safe**: the public response is always the same acknowledgement
(`"If the account requires verification, verification instructions have been sent"`) and
**never carries a token**, regardless of whether the email is unknown, malformed, or
belongs to an ACTIVE / SUSPENDED / DISABLED / PENDING account.

Service behaviour (`AuthService.resend_verification`): only a still-`PENDING_VERIFICATION`
account is issued a new token. Before issuing the replacement it invalidates any
previously issued, still-unused verification token for that user
(`EmailVerificationTokenRepository.consume_all_unconsumed_for_user`, using the existing
`consumed_at` column — **no migration**), so exactly one verification path is ever live.
Membership and customer tenancy are never touched. The raw token is returned from the
service **only** for the future 9.2.B `AuthEmailSender` boundary; the HTTP layer discards
it. Rate-limited per IP (`_resend_limiter`, 5 / 60 s). Audited as `verification_resent`
with safe metadata (no token, no email).

### 3. Password-reset → customer-provisioning consistency

Completing a password reset proves control of the email address, so a
`PENDING_VERIFICATION` user is activated exactly as email verification would activate
them. Previously `reset_password` activated the user but — unlike `verify_email` — did not
provision a personal customer tenant, leaving an ACTIVE user with no organization.

`reset_password` now calls the same canonical `provision_personal_customer` service on the
pending→active transition, inside the existing transaction and under the already-held
user-row lock. It is:

- **idempotent** — the provisioner skips when an active membership already exists;
- **invitation-precedence-preserving** — it skips when a valid pending invitation exists;
- **server-controlled** — no client-supplied customer/organization/role identifier;
- **scoped to the transition** — a reset for an already-ACTIVE user does not reach this
  branch, so a mere password change never creates tenancy;
- **atomic** — a provisioning failure rolls the whole reset back (the user stays pending
  with no tenant and the reset token is not consumed).

Session-revocation semantics are unchanged: reset still revokes every existing session.
Genuinely stranded historical accounts still have the authenticated
`/auth/customer-account/recover` fallback (never called automatically from the browser).

### 4. Route policy

The one new route is registered `PUBLIC` / `anonymous` (a public initiation path, like
register/verify/password-reset) in both the policy registry and the authentication gate's
public set, so the coverage test's "registry-public iff gate-public" invariant holds. No
other route changed disposition; no route is newly public beyond this one.

**Route inventory (independently verified from the live FastAPI graph):**

| | Before (9.1.A) | After (9.2.A) |
|---|---|---|
| Normalized entries | 84 | **85** |
| OpenAPI operations | 80 | **81** |
| Documentation routes | 4 | **4** |

### 5. Same-origin proxy expansion

`PROXY_ALLOWLIST` gains exactly five Phase 9.2 auth contracts, each an **exact path**
(no `auth/*` wildcard, no dynamic passthrough):

```
auth/register                POST
auth/verify-email            POST
auth/verification/resend     POST
auth/password-reset          POST
auth/password-reset/confirm  POST
```

Every existing entry is unchanged. The proxy keeps its server-only `API_UPSTREAM_ORIGIN`,
trusted-origin construction, traversal/encoded-separator rejection, method allow-list,
closed forwarded-header list, verbatim status-code preservation, `Set-Cookie` handling,
and `Cache-Control: no-store`.

### 6. Browser-safe typed contracts

`apps/web/src/lib/api/types.ts` adds `RegisterRequest` and `RegistrationResponse`; the
verification response reuses `User` and the acknowledgements reuse `MessageResponse`. No
internal IAM model, password hash, raw session token, audit record, or operator/platform
type is exposed. `portalApi` gains `register`, `verifyEmail`, `resendVerification`,
`requestPasswordReset`, and `confirmPasswordReset`, all routed through the same-origin
proxy. No credential or token is written to `localStorage`, `sessionStorage`, or
`IndexedDB`.

## Email delivery boundary (explicit non-scope)

Phase 9.2.A prepares **token issuance and contracts only**. No real provider (Resend,
Postmark, SES, SendGrid, Mailgun, …) is integrated, no provider credentials are added, and
no email templates exist. The service methods already return the raw token to their caller
so that **Phase 9.2.B owns actual transactional email delivery** by attaching an
`AuthEmailSender` port, without rewriting the registration / resend / reset domain rules.
Outside production the token continues to be surfaced by `register` via the existing
dev-only affordance; in production it is `null`.

## Migration result

No migration. Alembic head remains `20260813_0009_add_identity_access_organizations`;
`alembic check` reports no new upgrade operations. The verification-token invalidation
reuses the existing `consumed_at` column.

## Security guarantees (verified)

- Passwords, raw verification tokens, and raw reset tokens are never logged.
- Register and verification-resend rate limits are enforced server-side (per IP).
- Verification-resend, password-reset request, and login remain enumeration-safe.
- Session cookie (HttpOnly), CSRF handling, safe `next` redirect, and cookie attributes
  are unchanged.
- No browser-side session authority; no auth token in browser storage.
- The proxy remains closed (no `auth/*` wildcard, no browser-controlled upstream host).
- `/demo` and the authenticated `/portal` authorization boundary are unchanged; no
  payment/booking logic changed.

## Test results

- **API:** full `pytest` with database integration — see the phase report for the exact
  count (baseline 459 + the new registration-limit, verification-resend, and
  reset-provisioning suites).
- **Web:** full Vitest suite (baseline 76 + new proxy and client contract tests).
- Route-policy coverage asserts the exact **85 / 81 / 4** inventory.

## Not done in this slice

No `/register`, `/verify-email`, `/forgot-password`, or `/reset-password` UI; no email
provider/templates; no staging deployment; nothing from Phase 9.3. **Phase 9.2 is not
complete** — this is only the contract & backend-readiness slice.
