# ADR-039: API security migration — global fail-closed gate and principal-bound review

## Status

Accepted

## Context

Phases 2–7 endpoints were intentionally built before authentication existed. Turning
authentication on route-by-route risks leaving a sensitive endpoint accidentally
public. Phase 6 bound human review to an unauthenticated `actor_type` value supplied
in the request body — a placeholder that must now become a real authenticated
authorization boundary.

## Decision

- **Fail closed, globally.** Authentication is a dependency applied to the whole
  versioned router (`/api/v1`), so **every** route is authenticated unless explicitly
  classified PUBLIC. Public routes are a small allowlist: auth initiation/recovery,
  the signature-verified Stripe webhook, and read-only airport discovery. Platform
  routes (`/health`, `/ready`, `/openapi.json`, `/api/v1` root) live on the app,
  outside the gate.
- **A dependency, not middleware.** The gate is a FastAPI dependency so it shares the
  request session and honors test `dependency_overrides`; it resolves the session
  principal once, enforces CSRF for unsafe methods, attaches the principal to
  `request.state`, and rolls back its read so the endpoint's write transaction starts
  clean.
- **Route classification.** Routes are PUBLIC / AUTHENTICATED / CUSTOMER-SCOPED /
  OPERATOR-SCOPED / PLATFORM-REVIEWER / PLATFORM-FINANCE / PLATFORM-ADMIN. High-
  consequence actions are bound to authenticated principals with explicit
  permissions: compliance review requires `compliance.review` (held only by platform
  reviewer/admin/product-owner — so an **operator can never approve its own
  admission**, and a customer can never review compliance); financial onboarding is
  operator-scoped (`financial_onboarding.*`); refunds require `payment.refund`;
  organization/user administration requires the corresponding `admin.*` permission.
- **Tests over weakening.** Existing suites authenticate through shared fixtures
  (analogous to Phase 6 updating fixtures rather than loosening the gate). Pure
  domain/service tests that bypass HTTP are unchanged.

## Consequences

No sensitive route is accidentally public, and the security posture is regression-
tested (a route matrix plus explicit allow/deny tests). Phase 6 audit semantics are
preserved; the placeholder `actor_type` is now backed by a real authorized principal.
Per-resource ownership is enforced on the high-consequence routes; the same
`authorize(..., scope)` pattern extends to remaining customer/operator CRUD routes in
follow-up work without further architectural change.
