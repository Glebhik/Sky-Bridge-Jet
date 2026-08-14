# Phase 9.0.A-2 — Operator-Chain Resource Authorization

## Purpose

The second Phase 9 delivery unit is a **security gate**, not Operator Portal UI. It
closes the operator-tenant authorization debt: every operator-chain route now enforces
per-resource authorization server-side, so **Operator A can never read, create, modify,
submit, withdraw, confirm, reject, cancel, review, or otherwise act on Operator B's
resources**, and body-supplied `operator_id` values can never transfer ownership or
authorize a foreign operator.

It reuses the Phase 8 IAM primitives and the Phase 9.0.A-1 enforcement architecture
(ADR-040) — one seam (`modules/access.py`), the `Principal` / `ResourceScope` /
`is_authorized` policy, the declarative route-policy registry, and the append-only
`platform_authorization_exception` audit event. **No new authorization framework.**

This unit is deliberately bounded. It does **not** implement payment operations or
`payment.operate` (9.0.A-3), customer self-provisioning or customer-safe read models
(9.0.B), any Portal UI, a Next.js proxy, CORS changes, or any database migration.

## Enforcement architecture (ADR-042)

```
request → global auth gate (Phase 8) → route handler
                                          │
                                          ├─ active OPERATOR org resolved from principal (validated)
                                          ├─ operator ownership resolved by join (immutable → race-free)
                                          └─ authorize(principal, permission, ResourceScope.operator(owner))
                                                 allow · 403 (visible, no permission) · 404 (concealed)
```

- **Active OPERATOR organization**: auto-selected when the principal has exactly one
  eligible OPERATOR membership; otherwise a membership-validated `X-Organization-Id`
  is required. CUSTOMER/PLATFORM orgs can never be an ordinary operator context;
  client-supplied ids are never trusted. The Phase 9.0.A-1 customer context is
  unchanged.
- **Ownership** is resolved authoritatively by join (`aircraft.operator_id`,
  `offer.operator_id`, `booking.operator_id`, `evidence.operator_id`, and the
  `operator_id` path segment of the compliance routes) and is immutable, so
  resolve-then-act needs no lock for ownership (lifecycle still uses the services'
  existing row locks / optimistic checks).
- **Owner ids are principal-derived**: on create (aircraft, offer), the operator comes
  from the active org; a body `operator_id` may only confirm that tenant (mismatch →
  404). On confirm/reject, ownership is resolved from `booking.operator_id`; the body
  `operator_id` is used only for the pre-existing `operator_mismatch` domain check
  (409) and can never authorize a different operator. A platform principal with the
  relevant permission may act for an explicit existing operator — the audited platform
  exception.

### 401 / 403 / 404 / 409 (deny by default, unchanged)

| Code | When |
| --- | --- |
| 401 | not authenticated / session invalid or expired |
| 403 | authenticated, tenant visible, but missing the action permission |
| 404 | absent, or another operator tenant whose existence is concealed |
| 409 | visible resource, invalid lifecycle/concurrency transition |

## Operator-chain routes secured in this PR

| Route | Method | Rule |
| --- | --- | --- |
| `/operators` | POST | platform-admin only (`admin.organizations.manage`, B2); audited |
| `/operators/{id}` | GET | `operator.read`, owner==id, cross-operator 404 |
| `/aircraft` | POST | `operator.manage`, operator derived from active org; body id validated |
| `/aircraft/{id}` | GET | `operator.read`, via `aircraft.operator_id` |
| `/offers` | POST | `offer.manage`, operator derived; body id validated; aircraft↔operator (422) |
| `/offers/{id}` | GET | `offer.read`, via `offer.operator_id` |
| `/offers/{id}` | PATCH | `offer.manage` + owner + draft lifecycle |
| `/offers/{id}/submit`,`/withdraw` | POST | `offer.manage` + owner + lifecycle |
| `/bookings/{id}/confirm`,`/reject` | POST | `booking.decide` + owner via `booking.operator_id`; body id validated |
| `/bookings/{id}` | GET | operator owner (party) full; customer/platform per 9.0.A-1 |
| `/bookings/{id}/cancel` | POST | customer side (9.0.A-1) **+** operator owner (`booking.decide`) |
| `/operators/{id}/admission` | GET/POST | read `operator.read`; create `compliance.evidence.submit` |
| `/operators/{id}/admission/submit` | POST | `compliance.evidence.submit` + owner |
| `/operators/{id}/admission/audit-events` | GET | `operator.read` + owner |
| `/operators/{id}/evidence` | GET/POST | read `operator.read`; submit `compliance.evidence.submit` |
| `/evidence/{id}`,`/evidence/{id}/audit-events` | GET | `operator.read` via `evidence.operator_id` |
| `/operators/{id}/aircraft/{aid}/authorization` | GET/POST | read `operator.read`; create `compliance.evidence.submit`; aircraft↔operator 404 |
| `/operators/{id}/aircraft/{aid}/authorization/submit` | POST | `compliance.evidence.submit` + owner + aircraft 404 |
| `/operators/{id}/eligibility`,`/operators/{id}/aircraft/{aid}/eligibility` | GET | `operator.read` + owner + aircraft 404 |

Platform compliance **review** routes (`.../admission/review`, `/evidence/{id}/review`,
`.../authorization/review`) are unchanged — already bound to `compliance.review` in
Phase 8, which operators never hold.

## Platform-exception security auditing (ADR-042, reusing 9.0.A-1)

A **platform exception** is a successful access to an operator-owned resource by a
PLATFORM principal that is not a member of the owning operator organization. Every such
success is recorded **once, append-only** in `auth_audit_log` under the stable event
`platform_authorization_exception`.

- **Safe metadata only**: acting user, acting platform organization, normalized action
  id, permission, resource type, an opaque resource identifier, correlation id, and
  `result=allowed`. Never passwords, tokens, financial splits, customer/passenger PII,
  provider payloads, or request bodies.
- **Who does not trigger it**: an ordinary operator acting within its own tenant emits
  nothing; a denied operator/customer attempt is never recorded as a success.
- **Durability / transaction semantics**: a privileged **read** commits its audit
  record before the response is serialized; a privileged **write** passes an
  `on_commit` hook the service runs **inside its own transaction**, so the audit
  commits atomically with the mutation and rolls back with it. A failed mutation leaves
  no misleading successful-action record.

## Ownership immutability

The resolve-then-mutate pattern is race-free because operator ownership is immutable:
no route changes `aircraft.operator_id` / `offer.operator_id` / `booking.operator_id` /
evidence/admission operator ownership, and there is no operator ownership-transfer
endpoint. A future transfer endpoint must move ownership resolution, authorization, and
the mutation into one locked, atomic transaction (ADR-042). This PR adds no such
endpoint and no migration.

## Response confidentiality

The owning operator is a legitimate party to its own offer/booking commercial amounts
(it authors the offer; `platform_fee_minor` is derivable from the totals it sets), so
it receives the existing response. The customer-facing restriction (ADR-041) is
unchanged — customers still never receive `operator_amount_minor` / `platform_fee_minor`.
Cross-operator exposure is prevented by 404 concealment, proven by negative
serialization tests (`platform_fee_minor` / `operator_amount_minor` / `total_amount_minor`
absent from a cross-operator body). No new operator read-model is introduced.

## Route-policy registry & coverage invariant

`modules/route_policy.py` retires `PHASE_9_0A_2_PENDING` and reclassifies its 24 routes
to `PHASE_9_0A_2_BOUND`. The coverage invariant is unchanged — **76 OpenAPI operations +
4 documentation routes = 80** — and `tests/test_route_policy_coverage.py` additionally
asserts that exactly 24 routes are 9.0.A-2-bound, that no 9.0.A-2-pending disposition
remains, and that the 6 `PHASE_9_0A_3_PENDING` routes are untouched. The global
authentication gate is unchanged.

## Tests

- **Route-policy coverage**: 80/76/4 invariant; 24 bound; no 9.0.A-2 pending remains;
  9.0.A-3 pending preserved; unclassified/duplicate/misclassified-public all fail.
- **Active OPERATOR organization**: single auto-resolves; multiple require a validated
  `X-Organization-Id`; a foreign org id is rejected; a revoked membership grants no
  context; CUSTOMER and PLATFORM_ADMIN are not an operator context; customer context
  unchanged.
- **Cross-operator isolation**: real, distinct OPERATOR principals (never
  PRODUCT_OWNER); Operator A → Operator B is 404 on every bound route — operator,
  aircraft, offer, booking read, confirm/reject/cancel, admission, evidence, evidence
  audit-events, aircraft-authorization, and eligibility — with B's state proven
  unchanged.
- **Body-owner protection**: supplying another operator's `operator_id` on aircraft or
  offer create is a concealed 404; a body `operator_id` mismatch on confirm is a domain
  `operator_mismatch` (409), never an escalation.
- **Booking behaviour**: the owning operator confirms/rejects/cancels its booking;
  a customer cannot use operator decisions (404); repeated confirmation is 409; the
  customer paths from Phase 9.0.A-1 are intact.
- **Offer behaviour**: the owning operator creates (operator derived server-side) and
  drives update/submit/withdraw; a foreign operator cannot read or manage (404).
- **Compliance behaviour**: operator-self admission/evidence/authorization/eligibility
  only; an aircraft not of the path operator is a concealed 404; review stays
  platform-only (an operator cannot review its own evidence, 403).
- **Platform-exception audit (real PostgreSQL)**: a successful platform exception
  writes exactly one record with the correct actor and safe metadata; repeated reads
  append separate records; an ordinary operator in its own tenant and a denied
  cross-operator attempt write nothing; a customer cannot reach the branch; a
  privileged write audits atomically; a failed mutation writes no record; a failing
  audit hook rolls the mutation back.
- **Confidentiality**: a cross-operator offer/booking read is 404 with the commercial
  fields absent; the owning operator receives its own offer/booking.
- **Concurrency (real PostgreSQL)**: concurrent operator confirmations of the same
  booking transition once (200 + 409); a foreign operator cannot race a confirmation
  (intruder 404, owner 200, booking owned by the owner).

## Migration

**None.** Operator ownership resolves through existing relationships; no schema change.
`alembic check` reports no drift.

## Pending boundaries

- **9.0.A-3** — payment operations: the additive `payment.operate` permission
  (`PLATFORM_ADMIN`/`PRODUCT_OWNER` only; `PLATFORM_FINANCE_REVIEWER` stays read-only,
  per PO B1), and allocation/refund-list operator/platform scoping. `payment.refund`
  unchanged; customers/operators never receive `payment.operate`.
- **9.0.B** — customer self-provisioning and the customer-safe offer/booking/payment
  projections that flip the temporary customer 403s to safe 200s.
