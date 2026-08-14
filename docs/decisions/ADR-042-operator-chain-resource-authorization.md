# ADR-042: Operator-chain resource authorization (Phase 9.0.A-2)

## Status

Accepted (Phase 9.0.A-2 — operator chain). Extends ADR-040 to the OPERATOR tenant.
Payment operations (`payment.operate`) remain owned by Phase 9.0.A-3; customer
self-provisioning and customer-safe read models remain owned by Phase 9.0.B.

## Context

Phase 9.0.A-1 (ADR-040) closed the customer-chain authorization debt: every
customer-chain route enforces per-resource authorization, cross-tenant existence is
concealed as 404, and successful platform exceptions are append-only audited. The
operator chain — operators, aircraft, offers, operator-side booking decisions, and
operator compliance (admission / evidence / aircraft-authorization / eligibility) —
was still only *authenticated*, not *authorized per operator tenant*. Operator A could
therefore read or act on Operator B's resources, and body-supplied `operator_id`
values were trusted. This ADR closes that debt with the **same seam and the same
primitives** — no new authorization framework.

## Decision

**Reuse the Phase 8 primitives and the Phase 9.0.A-1 seam.** `modules/access.py`
gains an operator mirror of the customer functions, all expressed with the existing
`Principal`, `ResourceScope.operator(...)`, and `is_authorized`:

- **Active OPERATOR-organization context** (`active_operator_id`) is resolved
  server-side from the principal's memberships: auto-selected when exactly one
  eligible OPERATOR org exists, otherwise a membership-validated `X-Organization-Id`
  is required. A CUSTOMER or PLATFORM organization is never an ordinary operator
  context. The Phase 9.0.A-1 customer context is unchanged.
- **Operator ownership is resolved authoritatively by join** — `aircraft.operator_id`,
  `offer.operator_id`, `booking.operator_id`, `evidence.operator_id`, and the
  `operator_id` path segment of the compliance routes — on the request session. Because
  operator ownership is **immutable** (no route transfers it), resolve-then-act is
  race-free (see *Ownership immutability*).
- **Owner ids are principal-derived, never body-trusted.** On an operator create
  (aircraft, offer), the operator is derived from the active OPERATOR org; a body
  `operator_id` may only *confirm* that same tenant (a mismatch is concealed as 404).
  On confirm/reject, the operator is resolved from `booking.operator_id` and the body
  `operator_id` is used only for the pre-existing domain consistency check
  (`operator_mismatch`, 409) — it can never authorize a different operator.
- **Platform exceptions** (`require_operator_access` / `resolve_write_operator`): a
  PLATFORM principal holding the relevant permission may act cross-operator. This is the
  only cross-operator path and it is audited. `POST /operators` stays platform-admin
  controlled (`admin.organizations.manage`, PO decision B2) — no separate
  operator-onboarding permission and no operator self-provisioning.

**The 401 / 403 / 404 / 409 policy is unchanged** (deny by default): 401
unauthenticated; 403 authenticated + visible tenant but lacking the permission; 404
absent or another operator tenant whose existence is concealed; 409 a visible resource
with an invalid lifecycle/concurrency transition. Cross-operator UUID probing yields an
indistinguishable 404.

**Permissions come from the existing role matrix** (ADR-038): `operator.read` for
operator/aircraft/offer/compliance reads; `operator.manage` for aircraft management;
`offer.manage` for offer create/update/submit/withdraw; `booking.decide` for
confirm/reject and the operator side of cancel; `compliance.evidence.submit` for
operator-self admission/evidence/aircraft-authorization writes. Platform compliance
**review** stays `compliance.review` (ADR-037) — operators never gain it, so an
operator can neither review its own admission nor verify its own evidence.

**Platform exceptions are audited (append-only).** Successful operator platform
exceptions reuse the Phase 9.0.A-1 event `platform_authorization_exception` and the
`AuditRepository`, recording the acting user, the acting platform organization, and
safe metadata only (normalized action id, permission, resource type, an opaque
identifier, correlation id, `result=allowed`). Reads commit the record before the
response is serialized; writes pass an `on_commit` hook the service runs **inside its
own transaction**, so the audit commits atomically with — and rolls back with — the
mutation. Ordinary operator self-tenant actions record nothing; denied attempts never
record a success.

**Shared routes.** `POST /bookings/{id}/cancel` and `GET /bookings/{id}` keep their
Phase 9.0.A-1 customer/platform behaviour and gain the operator side (owner via
`booking.operator_id`): the owning operator may cancel and read its booking, a foreign
operator gets 404, and a platform actor is audited.

## Ownership immutability

Cross-transaction ownership resolution (resolve on the request session, roll back, then
mutate in the service transaction) is safe only because operator ownership is immutable:
no route changes `aircraft.operator_id`, `offer.operator_id`, `booking.operator_id`, or
evidence/admission operator ownership, and there is no operator ownership-transfer
endpoint. **A future ownership-transfer endpoint must move ownership resolution,
authorization, and the mutation into one locked, atomic transaction** (as ADR-040 also
requires for the customer chain). This PR adds no such endpoint and no migration.

## Response confidentiality

The offer/booking commercial amounts (`operator_amount_minor`, `platform_fee_minor`,
`tax_amount_minor`, `total_amount_minor`) are the operator/platform commercial split.
The **owning operator is a legitimate party** to its own offer/booking: it authors the
offer (it sets `operator_amount_minor`), and the platform fee is arithmetically
derivable from the totals it sets. Exposing these to the *owning* operator is therefore
not a confidentiality violation; the customer-facing restriction of ADR-041 is
unchanged (customers still never receive these fields). Cross-operator exposure is
prevented by 404 concealment, proven by negative serialization tests. No new operator
read-model or projection is introduced. (This is the deliberate, documented "smallest
bounded solution" for these existing responses.)

## Route-policy registry

The `PHASE_9_0A_2_PENDING` disposition is retired; its 24 routes are reclassified to a
new `PHASE_9_0A_2_BOUND`. The coverage invariant is unchanged — 76 OpenAPI operations +
4 documentation routes = 80 — and the automated test additionally asserts that no
operator-chain route remains pending and that the 6 `PHASE_9_0A_3_PENDING` routes are
untouched.

## Consequences

Operator A can never read or act on Operator B's resources; body-supplied `operator_id`
cannot transfer ownership or authorize a foreign operator; cross-operator existence is
concealed; platform exceptions are explicit and audited. The same
`authorize(..., ResourceScope.operator(...))` pattern and the same registry now cover
both tenant chains. Remaining debt is explicitly bounded: payment operations
(`payment.operate`, 9.0.A-3) and customer self-provisioning / customer-safe projections
(9.0.B).
