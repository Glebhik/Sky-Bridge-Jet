# ADR-040: Per-resource authorization, the route-policy registry, and the 401/403/404 policy

## Status

Accepted (Phase 9.0.A-1 — customer chain). Operator chain (9.0.A-2) and payment
operations (9.0.A-3) are explicitly pending.

## Context

Phases 2–7 API routes were built before authentication and, after Phase 8, were only
*authenticated* — not *authorized per resource*. Owner identifiers (`customer_id`,
`operator_id`) were trusted from request bodies, and no route confined a caller to
its own tenant. Authentication alone is insufficient; the frontend is never an
authorization boundary. Phase 9 must close this debt before any Customer Portal
feature, starting with the customer chain.

## Decision

**One enforcement seam, reusing Phase 8 primitives.** A small module
(`modules/access.py`) resolves ownership and makes the allow/deny decision using the
existing `Principal`, `ResourceScope`, and `is_authorized`. It adds no competing
framework.

- **Active CUSTOMER-organization context** is resolved server-side from the
  principal's memberships (auto-selected when one, an explicitly validated
  `X-Organization-Id` when several). An OPERATOR/PLATFORM org can never serve as a
  customer context, and a client-supplied organization/customer id is never trusted.
- **Ownership is resolved authoritatively by join** (`trip.customer_id`;
  passenger→customer; offer/booking→trip→customer; payment→booking→trip→customer),
  on the request session inside the operation's consistency boundary. Because
  customer ownership is **immutable**, the resolve-then-act sequence is race-free.
- **Owner ids are principal-derived, never body-trusted.** On create, the customer is
  derived from the active organization; a body `customer_id` may only *confirm* that
  same tenant (a mismatch is concealed as 404). A platform principal holding
  `customer.write` may act for an explicit, existing customer — the single, audited
  platform exception.

**The 401/403/404/409 policy** (deny by default):

| Code | Meaning |
| --- | --- |
| 401 | missing/invalid/expired authentication |
| 403 | authenticated, visible tenant, but lacking the action permission |
| 404 | resource absent, or in another tenant whose existence must be concealed |
| 409 | valid, visible resource but an invalid lifecycle/concurrency transition |

Cross-tenant UUID probing therefore yields an indistinguishable 404 whether or not
the resource exists. Error bodies carry no confidential tenant identifiers; platform
exceptions are permission-bound.

**A declarative route-policy registry** (`modules/route_policy.py`) gives *every*
registered route/method an explicit disposition (PUBLIC / ALREADY_BOUND /
PHASE_9_0A_1_BOUND / PHASE_9_0A_2_PENDING / PHASE_9_0A_3_PENDING). An automated
coverage test introspects the live FastAPI app (76 OpenAPI operations + 4
documentation routes = 80 normalized entries) and **fails** if any route is
unclassified, omitted, duplicated, or a protected route is marked public. A route can
never become accessible by being forgotten. Pending dispositions never weaken the
global authentication gate.

## Consequences

Customer A can never read or act on Customer B's resources; body-supplied owner ids
cannot transfer ownership; cross-tenant existence is concealed. The same
`authorize(..., ResourceScope.…)` pattern and registry extend to the operator chain
(9.0.A-2) and payment operations (9.0.A-3) without new architecture. Responses that
still expose confidential fields (`platform_fee_minor`, `operator_amount_minor`) are
not broadened to customers here — see ADR-041.
