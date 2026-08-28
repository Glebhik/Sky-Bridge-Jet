# Phase 9.8.A — Platform Compliance Review Center

Canonical base: `43cbec80f0754f50fac7473f046746fdf2aa3707`.

## Purpose and authority

The center gives principals holding canonical `compliance.review` permission a bounded internal workflow for operator admissions, compliance evidence, and operator-aircraft authorizations. `PLATFORM_COMPLIANCE_REVIEWER`, `PLATFORM_ADMIN`, and `PRODUCT_OWNER` hold that permission. Support and finance-reviewer roles do not.

The API remains authoritative. Review actor type and reference are derived from the authenticated principal; browser payloads contain only action, controlled reason code, and optional bounded internal note. Platform permissions are principal-global under the existing IAM model. No browser-supplied reviewer or target organization is authoritative.

## Queue and detail contracts

Each resource has an exact `GET /api/v1/platform/compliance/<resource>` collection with `limit` 1–100, non-negative `offset`, and optional canonical status filter. Ordering is deterministic: submitted time ascending with nulls last, then created time and UUID ascending. SQL applies filters, ordering, limit, and offset.

Dedicated reviewer projections expose operator legal/trading identity and only decision-relevant resource metadata. They exclude customer/passenger/Booking/Offer/payment/provider and operator financial data. Evidence responses expose `has_storage_object`, never `storage_object_reference`, bucket keys, filesystem paths, document bytes, or download capability.

Exact detail and review routes use the platform projection. Exact audit routes return at most 100 factual events (Web requests 50). Audit rows remain append-only.

## Canonical workflows

- Admission: DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED/REJECTED; APPROVED → SUSPENDED; SUSPENDED → APPROVED via restore.
- Evidence: SUBMITTED → UNDER_REVIEW → VERIFIED/REJECTED.
- Aircraft authorization: the same review/suspend/restore semantics as admission.

Existing `ComplianceService` transition validators, row locks, eligibility evaluator, and audit writer are reused. Concurrent or stale decisions fail with conflict; the browser never retries a mutation automatically. A conflict triggers at most one authoritative refresh.

## Query and storage boundaries

Collections use one joined SQL query and never fetch operator or aircraft per row. Detail reads have a fixed query shape. No migration was introduced: the current schema supports correctness and bounded result materialization. Index additions require separate measured production evidence.

Evidence review in this slice is metadata-based. Actual document viewing is explicitly deferred until a safe authenticated document-delivery boundary exists.

## Web and proxy

Web routes:

- `/platform/compliance`
- `/platform/compliance/admissions/[id]`
- `/platform/compliance/evidence/[id]`
- `/platform/compliance/aircraft-authorizations/[id]`

The platform layout requires an authenticated PLATFORM membership plus `compliance.review`. The API repeats final authorization. The same-origin proxy allow-lists only the three collection GETs and exact UUID detail/review/audit shapes. There is no `/platform/*` wildcard.

Reads use `cache: no-store`, same-origin credentials, AbortSignal, and request epochs. Filter/page/detail changes abort and invalidate old reads. Each detail instance has an immutable `(kind, id, generation)` identity; the keyed resource boundary creates a new monotonic generation even for an A → B → A navigation. Abort is an optimization, while the resource identity plus read epoch is the correctness gate for detail and audit results.

Confirmation captures the exact `(kind, id, generation, action)` that displayed it and is invalidated by any resource change. A mutation receives its own synchronous token bound to that confirmation identity. Success, conflict recovery, unknown-outcome handling, and final cleanup may update state only while that exact token and resource generation still own the view. Late success is discarded; a stale 409 performs no refresh; a stale unknown outcome shows no error; and an old `finally` cannot release a newer resource's guard. A current 409 performs at most one authoritative refresh without mutation retry. A current unknown outcome clears confirmation and disables further review decisions until an explicit authoritative refresh succeeds. Mutations use CSRF, disabled controls, `aria-busy`, deliberate confirmation, and never retry automatically.

## Privacy, language, and accessibility

Internal notes remain platform-only. No sensitive value is placed in a URL. Copy describes Sky Bridge Jet marketplace eligibility, not airworthiness or regulatory certification. Controls are keyboard accessible, labelled, textually stateful, focus-visible, and responsive from 320px upward.

## Deferred

Phase 9.8.A adds no payment, refund, payout, Stripe, notification, support, document-storage, fleet-management, Booking intervention, or FlightOperation authority. Financial operations remain deferred to Phase 9.8.B.
