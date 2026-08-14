# Phase 9.0.A-3 — Payment Operational Authorization

## Purpose

The third Phase 9 delivery unit is a **security gate**, not a payment-provider
integration. It closes the remaining authorization debt on the existing payment routes:
customers and operators cannot perform internal payment operations, `PLATFORM_FINANCE_REVIEWER`
is strictly read-only, only `PLATFORM_ADMIN`/`PRODUCT_OWNER` may operate payments, every
successful payment mutation is append-only audited, and the confidential allocation /
refund-list reads are platform-read-only. No real payment gateway and no customer
payment-start experience are introduced.

It reuses the Phase 8 permission matrix and the Phase 9.0.A-1/A-2 seam and append-only
audit infrastructure — no new authorization framework.

## Permission model (ADR-043)

| Role | payment.read | payment.operate | payment.refund |
| --- | --- | --- | --- |
| PRODUCT_OWNER | yes | **yes** | yes |
| PLATFORM_ADMIN | yes | **yes** | yes |
| PLATFORM_FINANCE_REVIEWER | yes | **no** | **no** (removed — ADR-043) |
| PLATFORM_SUPPORT | yes | no | no |
| CUSTOMER_* | read only | no | no |
| OPERATOR_* | scoped read only | no | no |

`payment.operate` is additive and platform-only. `payment.refund` is unchanged and
**separate** — the refund capability is never folded into `payment.operate`. Phase 8
had granted `PLATFORM_FINANCE_REVIEWER` the `payment.refund` permission; the Product
Owner directed that this role be strictly read-only, so ADR-043 removes that grant (no
existing test depended on it).

## Routes secured in this PR (6 → PHASE_9_0A_3_BOUND)

| Route | Method | Rule |
| --- | --- | --- |
| `/bookings/{id}/payment` | POST | `payment.operate`; internal/trusted (B3/D); Booking resolved server-side; audited |
| `/payments/{id}/authorize` | POST | `payment.operate`; lifecycle/idempotency preserved; audited |
| `/payments/{id}/capture` | POST | `payment.operate`; lifecycle/idempotency preserved; audited |
| `/payments/{id}/void` | POST | `payment.operate`; lifecycle/idempotency preserved; audited |
| `/payments/{id}/allocation` | GET | platform `payment.read` only; customer/operator 403; cross-tenant 404; audited |
| `/payments/{id}/refunds` | GET | platform `payment.read` only; customer/operator 403; cross-tenant 404; audited |

Already-bound (unchanged): `POST /payments/{id}/refunds` (`payment.refund`), `GET /payments/{id}`
and `GET /bookings/{id}/payment` (Phase 9.0.A-1 confidential), `POST /webhooks/stripe`
(public, signature-authenticated).

## Enforcement

- **Operations** (create/authorize/capture/void) use a global `require_permission(payment.operate)`
  dependency — no per-tenant scope, since these are platform-internal actions. The payment
  service still enforces payment/booking existence (404), lifecycle/idempotency/amount
  invariants (409), and concurrency (row locks). Having `payment.operate` bypasses none of
  these.
- **Refund** keeps its `require_permission(payment.refund)` gate and adds an append-only
  audit record; the capability and its holders are unchanged.
- **Allocation / refund-list reads** resolve ownership through `Payment → Booking →
  TripRequest → Customer` and `Payment → Booking → Operator` and apply a
  platform-read-only policy: a platform `payment.read` viewer is served (and audited); an
  owning customer or owning operator is temporarily denied (403 — no safe financial
  projection yet, Phase 9.0.B); a cross-tenant probe is concealed (404). No body id is
  trusted.

## Ownership & body-id treatment

Owner identifiers are principal-/server-derived. `POST /bookings/{id}/payment` resolves the
Booking from the path and trusts no body ownership id. `authorize/capture/void` resolve the
Payment (and its Booking) from the path. Allocation/refund-list ownership is resolved by
join. No route accepts a client-supplied customer/operator/payment ownership identifier as
an authorization input.

## Payment-operation audit (ADR-043)

Stable append-only event **`payment_operational_action`** in `auth_audit_log` for every
**successful** internal mutation: create, authorize, capture, void, refund. Records acting
user, acting platform org, normalized action id, permission used (`payment.operate`, or
`payment.refund` for a refund), resource type + opaque id, `result=allowed`, and the
correlation id. Never amounts, provider references, tokens, card/bank data, request bodies,
webhook payloads, margins, or PII.

Transaction semantics: the hook runs **inside the service transaction** and **only on the
success path**, so the audit commits atomically with the mutation; a decline / failed
lifecycle / denied action / idempotent replay records nothing; an audit-hook failure rolls
the mutation back. Platform allocation/refund-list **reads** use the read event
`platform_authorization_exception` — a read is never mislabelled as a mutation.

## Webhook boundary

`POST /api/v1/webhooks/stripe` remains public and signature-authenticated: no session, no
`payment.operate`. Signature verification, replay/idempotency, and event deduplication are
unchanged. Regression tests confirm the permission work does not apply to or break the
webhook.

## Error policy

401 unauthenticated · 403 authenticated but lacking the permission in a visible context ·
404 absent or a foreign tenant whose existence is concealed · 409 a visible resource with an
invalid lifecycle/idempotency/concurrency transition. Error bodies expose no provider
identifiers, amounts, allocation data, or audit payloads.

## Tests

- **Route-policy coverage**: 80/76/4; 6 routes `PHASE_9_0A_3_BOUND`; no pending remains;
  unclassified/duplicate/contradictory/misclassified-public all fail.
- **Permission matrix**: `payment.operate` only PLATFORM_ADMIN + PRODUCT_OWNER; finance
  reviewer read-only (no operate, no refund); `payment.refund` separate and platform-only;
  no customer/operator role holds operate or refund.
- **Create**: PLATFORM_ADMIN/PRODUCT_OWNER create (idempotent duplicate returns the same
  payment); finance reviewer/customer/operator denied (403) with no payment created.
- **Authorize/capture/void**: platform actors succeed through the lifecycle; finance
  reviewer/customer/operator denied (403) with state unchanged; invalid lifecycle is 409.
- **Refund**: finance reviewer/customer/operator denied (403); PRODUCT_OWNER (payment.refund)
  succeeds; refund stays gated to `payment.refund`.
- **Allocation/refund-list reads**: platform payment.read viewers (finance reviewer,
  PRODUCT_OWNER) allowed; owning customer/operator 403; cross-operator/unknown 404;
  confidential fields absent from denied bodies.
- **Audit (real PostgreSQL)**: each successful operation writes exactly one record with safe
  metadata; denied/failed/replayed operations write none; a failing audit hook rolls the
  mutation back.
- **Concurrency (real PostgreSQL)**: concurrent captures serialize (200 + 409); the payment
  transitions once.
- **Webhook regression**: the Stripe webhook stays public/signature-authenticated and is not
  blocked by the auth/permission layer.

## Migration

**None.** `payment.operate` is an enum value; ownership resolves through existing
relationships. `alembic check` reports no drift.

## Pending boundaries

- **9.0.B** — customer self-provisioning and the customer/operator-safe financial
  projections that flip the temporary allocation/refund-list 403s to safe reads, plus the
  customer-safe payment-status view.
