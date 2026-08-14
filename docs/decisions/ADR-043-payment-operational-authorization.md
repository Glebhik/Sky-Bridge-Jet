# ADR-043: Payment operational authorization (Phase 9.0.A-3)

## Status

Accepted (Phase 9.0.A-3 — payment operations). Extends ADR-040/042 to the payment
routes. Customer self-provisioning and customer-safe projections remain owned by Phase
9.0.B. This is an authorization/security unit, **not** a payment-provider integration:
no live provider authorization/capture and no customer payment-start experience.

## Context

After Phase 9.0.A-2, the customer and operator chains are authorized per resource, but
the payment routes were still only *authenticated*: internal payment creation and the
authorize/capture/void operations had no per-capability gate, and the allocation and
refund-list reads exposed the internal operator/platform financial split and provider
references to any authenticated principal. This ADR closes that debt using the existing
centralized permission matrix and the Phase 9.0.A-1/A-2 append-only audit seam — no new
authorization framework.

## Decision

**One additive permission, centrally defined.** `payment.operate` is added to the
`Permission` vocabulary (ADR-038) and granted **only** to `PLATFORM_ADMIN` and
`PRODUCT_OWNER`. It is never granted to `PLATFORM_FINANCE_REVIEWER`, to any customer
role, or to any operator role. It gates the internal/trusted payment operations
(create/authorize/capture/void). Enforcement is a global permission dependency
(`require_permission(PAYMENT_OPERATE)`); there is no per-tenant scope because these are
platform-internal actions.

**`payment.refund` is unchanged and separate.** Refunds continue to require the existing
`payment.refund` permission — the capability is **not** folded into `payment.operate`.
`payment.refund` remains held only by `PLATFORM_ADMIN` and `PRODUCT_OWNER`.

**Finance-reviewer correction.** Phase 8 granted `PLATFORM_FINANCE_REVIEWER` the
`payment.refund` permission. The Product Owner's Phase 9.0.A-3 decision is that this role
must be **strictly read-only** (Section 1.B). The discrepancy was inspected and reported
before changing anything; on the Product Owner's explicit direction, `payment.refund` is
**removed** from `PLATFORM_FINANCE_REVIEWER`. The role retains `payment.read` (visibility),
`finance.review`, `financial_onboarding.read`, and `operator.read`, and holds **no**
payment mutation capability (neither `payment.operate` nor `payment.refund`). No existing
test depended on the removed grant.

**Internal payment creation** (`POST /bookings/{id}/payment`) is an internal/trusted
platform action (PO decision B3/D): it requires `payment.operate`, resolves the Booking
server-side, trusts no body-supplied ownership identifier, preserves the
one-payment-per-booking idempotency invariant and the Booking-lifecycle/amount rules, and
is not exposed to customers, operators, `PLATFORM_FINANCE_REVIEWER`, or any frontend.

**Allocation and refund-list reads** (`GET /payments/{id}/allocation`,
`GET /payments/{id}/refunds`) are **platform-read-only**. Their responses expose the
internal operator/platform split, settlement eligibility, and provider references — data
not approved for ordinary operators or customers. Only a platform viewer holding
`payment.read` receives them; an owning customer or owning operator is **temporarily
denied (403)** (no customer/operator-safe financial projection exists yet — Phase 9.0.B);
any other principal or a cross-tenant probe receives **404** (existence concealed).
Ownership is resolved through `Payment → Booking → TripRequest → Customer` and
`Payment → Booking → Operator`. This is the deliberate "retain a temporary denial" option
(the smallest bounded solution); no new operator/customer read-model is introduced.

**The 401/403/404/409 policy is unchanged** (deny by default). Error bodies carry no
provider identifiers, amounts, allocation data, or confidential audit payloads. Having
`payment.operate` never bypasses payment/booking existence, lifecycle, amount invariants,
idempotency, concurrency, refund rules, or webhook authenticity — the service invariants
still run.

## Payment-operation auditing

A distinct, stable append-only security event `payment_operational_action` records every
**successful** internal payment mutation (create, authorize, capture, void, refund) in the
existing Phase 8 `auth_audit_log` via `AuditRepository`. The record identifies the acting
user, the acting platform organization, the normalized action id, the permission used
(`payment.operate`, or `payment.refund` for a refund), the resource type + opaque
identifier, `result=allowed`, and the correlation id — **never** amounts, provider
references, tokens, card/bank data, request bodies, webhook payloads, margins, or PII.

The hook runs **inside the payment service's transaction** via `on_commit` and **only on
the success path**, so:

- a successful mutation commits its audit atomically with the state change;
- a provider decline / failed lifecycle transition / denied action records **nothing**;
- an idempotent replay (no new mutation) records **nothing** (no duplicate);
- an audit-hook failure rolls the mutation back.

Payment mutations use `payment_operational_action`; the allocation/refund-list platform
reads continue to use the read event `platform_authorization_exception`, so a read is
never mislabelled as a payment mutation.

## Webhook boundary

`POST /api/v1/webhooks/stripe` remains a signature-authenticated public system route. It
does not require a user session or `payment.operate`; signature verification, replay
handling, and provider-event deduplication are unchanged. No live provider integration is
added.

## Route-policy registry

The `PHASE_9_0A_3_PENDING` disposition is retired; its 6 routes are reclassified to
`PHASE_9_0A_3_BOUND`. The coverage invariant is unchanged — 76 OpenAPI operations + 4
documentation routes = 80 — and the automated test additionally asserts that no
payment-operation route remains pending.

## Consequences

Customers and operators cannot perform any internal payment operation or refund;
`PLATFORM_FINANCE_REVIEWER` is strictly read-only; only `PLATFORM_ADMIN`/`PRODUCT_OWNER`
operate payments; every successful payment mutation is append-only audited atomically;
allocation/refund-list reads leak no confidential financial data. No database migration is
required (ownership resolves through existing relationships; `payment.operate` is an enum
value). Remaining debt is Phase 9.0.B: customer self-provisioning and the customer/operator
safe financial projections that flip the temporary 403s to safe reads.
