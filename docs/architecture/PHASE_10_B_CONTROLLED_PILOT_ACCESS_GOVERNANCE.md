# Phase 10.B — Controlled pilot access and governance

## Decision

Pilot B admission is an organization-level, server-authoritative domain fact. It is deliberately separate from identity registration, verified email, IAM membership, organization activation, operator compliance, and commercial state. Existing registration remains identity-only: it never creates pilot admission.

The durable singleton governance state defaults to `INTERNAL_ONLY`. `CONTROLLED_EXTERNAL` requires an exact `ACTIVE` customer/operator participant for every new-journey boundary. `PAUSED` fails closed for those boundaries while preserving historical reads, existing bookings, payments, flight operations, compliance/finance recovery, and notification delivery.

## Data and state machines

- `pilot_governance_state`: fixed singleton UUID, mode, independent test/fake payment-initiation switch, optimistic version, timestamp.
- `pilot_participants`: unique existing organization UUID, factual `CUSTOMER`/`OPERATOR` kind, status, optimistic version, timestamps.
- `pilot_governance_audits`: append-only actor, exact resource, action, previous/new factual state, bounded reason, timestamp.
- Participant transitions: `INVITED → ACTIVE`; `ACTIVE ↔ SUSPENDED`; `ACTIVE|SUSPENDED|INVITED → REVOKED`. `REVOKED` is terminal in this phase.

There is no bearer invitation token and therefore no invite secret to persist, log, or expose. Platform staff selects an existing organization; customer/operator browsers cannot self-admit or set governance state.

## Authority and projections

`pilot.manage` belongs only to `PLATFORM_ADMIN` and `PRODUCT_OWNER`. `PLATFORM_SUPPORT` receives `pilot.read` only. Other platform roles and every customer/operator role receive neither. Routes use exact permission dependencies; no generic superuser path exists.

Platform projections contain organization UUID/name/type, factual pilot state/version/timestamps, and bounded audit facts. They omit user email, membership details, customer/passenger PII, operator private/compliance evidence, payment/provider/refund data, secrets, and internal free text. Customer/operator projections are not added.

## Enforcement boundary

The gate is called after authoritative active-organization/resource ownership resolution and before the domain mutation. It covers customer trip creation/submission, offer selection, booking creation, payment initiation; and operator opportunity discovery, offer create/edit/submit, and booking confirm/reject. Canonical compliance remains an additional independent requirement. Safe history, cancellations/recovery, compliance review, payment reconciliation, and operational reads remain available.

The independent payment switch only blocks new customer payment initiation in external mode. It does not activate live Stripe and cannot turn a fake/test provider into real money. No notification switch is introduced because suppressing already-required critical delivery during a pause would be unsafe.

## Concurrency and failure behavior

Participant creation locks the target organization and relies on a unique constraint for global deduplication. Governance and participant mutations lock their exact row and require `expected_version`; stale commands return `409`. Exact repeats are no-ops and add no audit event. The Web disables duplicate commands, asks for explicit confirmation, never retries mutations after `409` or an unknown network outcome, and refreshes all authoritative state with abort/epoch protection so A→B→A responses cannot overwrite current state.

The fixed singleton is inserted by migration `20260830_0013`. Missing singleton state is fail-closed. Collections require `limit` 1–100 and non-negative `offset`, use deterministic indexed ordering, and load participant plus organization name in one query.

## Web and proxy

`/platform/pilot` is available only to authenticated platform members with `pilot.read`. The same-origin proxy adds only the five exact collection/state paths plus two canonical-UUID patterns; methods are individually bound. The page provides factual global controls, invite-by-existing-organization, participant transitions, bounded pagination, recent audit, confirmation, loading/empty/error states, and responsive keyboard-visible controls.

## Explicit exclusions

No Terms/Privacy acceptance, MFA, production email, live Stripe, refunds, payouts, chargebacks, completion lifecycle, aircraft amendments, support-case system, dependency, or external asset is introduced. Pilot A remains available through `INTERNAL_ONLY`; external Pilot B remains no-real-money unless later governance and professional-review gates authorize a separate phase.
# Audit remediation

The independent audit found that the default participant list was result-bounded
but not database-work-bounded: it ordered by `(created_at, id)` without an index
beginning with those columns. At 50,000 participants, PostgreSQL therefore used a
participant `Seq Scan`, hash join, and top-N `Sort` before `LIMIT 20` (50,000 rows
examined, about 46 ms in the disposable audit runtime).

Migration `0013` and ORM metadata now define
`ix_pilot_participants_created_id (created_at, id)`. The same 50,000-row query uses
that index, examines 20 participant rows, performs no explicit sort, and completed
in about 0.1–0.5 ms in repeated repair runs. The index-backed shape also held at
1,000 and 10,000 rows and for limits 1, 20, and 100. A PostgreSQL plan regression
test locks the production ordering, named index, absence of participant sequential
scan/sort, fixed query count, pagination separation, and tied-timestamp ID order.
Existing status/type indexes remain appropriate for filtered reads; no additional
index was justified.

`PLATFORM_SUPPORT` retains factual read access, but the Web surface does not render
invite, participant-transition, global-mode, or payment-switch controls without
`pilot.manage`. `CONTROLLED_EXTERNAL` is explicitly an invite-only controlled
external pilot with **NO REAL MONEY**.

## Active-organization authority remediation

The independent re-audit found a BLOCKER in controlled mutations: resource checks
could authorize against any matching membership in the principal even when the
request selected a different organization. Consequently, an ACTIVE organization A
could lend authority while suspended or otherwise non-owning organization B was the
explicit `X-Organization-Id`. Platform pilot routes similarly checked a permission
from any platform membership without binding it to the selected organization.

The repaired invariant is that the validated active organization is the request
tenant. Customer mutations first resolve the canonical active CUSTOMER membership,
derive immutable ownership through the TripRequest/Booking relationship, and require
equality before participant or payment-switch evaluation. Operator mutations do the
same through the Offer/Booking operator owner before pilot and compliance checks.
Cross-tenant mismatches use the established `404` concealment posture and do not
reveal the foreign participant or compliance state. Platform pilot routes require
the selected organization itself to be PLATFORM and require `pilot.read` or
`pilot.manage` on that exact membership; wrong-kind contexts return `403`.

Direct PostgreSQL/API regressions lock Customer A→B→A and Operator A→B→A switching,
including trip submit, offer select/update/submit, booking create/confirm/reject, and
payment initiation. Platform P→Customer→P coverage locks collection reads,
participant creation/status mutation, global-state mutation, and the support
read-only matrix. These tests prove that switching back restores valid authority
without sticky or union-of-memberships behavior. The pre-existing participant
index/query-plan regression remains unchanged.
