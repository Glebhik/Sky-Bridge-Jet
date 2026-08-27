# Phase 9.7.A — Operator Offer Management

## Identity and prerequisites

This implementation is based on `65dac8c3798354a20e806eae132528ea3bddd154`. It consumes the merged A0 operator-safe opportunity projection and A1 active-operator aircraft discovery/scoped Offer creation boundary. No API route, database schema, migration, or dependency is added.

## Web route and navigation

`/operator/opportunities` is protected by the existing operator server layout. The layout exposes only the minimal `Opportunities` and `Bookings` navigation; it does not introduce an operator dashboard. The page derives operator memberships and role capabilities from the authenticated server session.

## Closed proxy and client

The same-origin proxy adds only:

- `GET me/operator-opportunities`
- `GET me/operator-aircraft`
- `POST me/operator-offers`
- `GET|PATCH offers/:uuid`
- `POST offers/:uuid/submit`
- `POST offers/:uuid/withdraw`

UUID, segment count, and method matching remain exact; no wildcard or arbitrary upstream target exists. The typed browser client uses `credentials: same-origin`, `cache: no-store`, the active `X-Organization-Id`, CSRF for unsafe methods, and abort signals for reads. It never sends `operator_id` or bearer credentials.

Successful operator Offer responses are projected by the server-side proxy before reaching browser network. The projection retains only owned Offer editing facts and removes `operator_id`, platform fee, customer total, provider/payment fields, and any unexpected future fields. Upstream error status/envelopes remain intact and are rendered only as safe UI copy.

## Roles and organizations

| Role | Read | Create/edit/submit/withdraw |
| --- | --- | --- |
| OPERATOR_ADMIN | yes | yes |
| OPERATOR_SALES | yes | yes |
| OPERATOR_OPERATIONS | yes | no |
| OPERATOR_FINANCE | yes | no |
| OPERATOR_COMPLIANCE | yes | no |

Mutation controls are absent from the DOM for read-only roles. The API remains final authority. One membership is selected automatically; multiple memberships require an explicit choice before any load. A change synchronously changes the active organization, aborts reads, advances a request epoch, and clears opportunities, aircraft, editor, details, and errors so data from organization A cannot land in B. Every asynchronous read and mutation captures its `(organizationId, epoch)` scope; success, error, conflict refresh, and pending-state writes are accepted only while that exact scope remains current. This also rejects an old A response after an A → B → A sequence.

## Marketplace, aircraft, and lifecycle

The list renders only A0 facts: trip status, route legs, departure, passenger count, creation date, and the active operator's own Offer IDs/statuses. It does not load Offer details per card. One bounded aircraft collection is loaded in parallel once per selected organization. Only active, eligible returned aircraft appear in the editor, while ownership, compliance, and trip eligibility are always revalidated by the API.

Offer creation uses `POST /me/operator-offers`; trip identity comes from the opportunity and aircraft identity from the A1 list. DRAFT detail is loaded only when explicitly edited. Canonical responses replace local state after create, update, submit, or withdraw. DRAFT permits edit/submit, SUBMITTED permits withdraw, and SELECTED/WITHDRAWN/EXPIRED or unknown future states are read-only.

Operator amount and tax are entered as decimal strings and converted through digit/BigInt arithmetic to integer minor units. Only EUR, GBP, and USD are offered. There is no floating-point financial authority, FX, platform-fee editing, customer total, payment, payout, capture, void, or refund behavior. Validity, operator notes, cancellation policy, included services, and excluded services map only to existing canonical fields.

## Concurrency, recovery, and freshness

A synchronous per-organization token guard rejects overlapping create/edit/submit/withdraw activation before React can rerender; pending controls are also disabled. A switch does not destroy the originating organization's in-flight token: only the operation holding the exact token may release it. This permits an independent organization B operation while A is pending without allowing A's later `finally` to release B's guard. Financial state is never optimistic. A current-scope 409 triggers exactly one owned-Offer GET and never retries the mutation; a stale 409 performs no refresh. Other failures retain safe known state where possible and never expose raw backend details.

Freshness consists only of initial load, explicit manual refresh, authoritative mutation responses, and the single conflict refresh. There is no polling, timer, WebSocket, SSE, subscription, or request-per-card pattern.

## Privacy and security

Neither DOM nor the 9.7.A browser response projection contains customer UUID/name/email/phone, passenger identity, DOB, nationality, passport, private requirements/assistance notes, competitor offers, foreign operator amounts, platform fee, customer total, or payment/provider data. The proxy adversarial suite covers wrong methods, malformed UUIDs, encoded separators, traversal, extra segments, adjacent/admin/payment/webhook families, and aircraft mutations.

## Verification

Focused tests cover proxy policy/projection, exact client transport, money conversion, role controls, multi-org gating, no N+1, creation, lifecycle display, synchronous mutation guarding, and 409 recovery. The multi-organization suite deliberately resolves delayed detail/create/edit/submit/withdraw success, 403/404/network failures, conflict responses, and read responses after switches, including A → B → A epochs and independently pending A/B mutations. Final verification also includes the full API and Web suites, static gates, production build and bundle scan, route/Alembic locks, disposable PostgreSQL real-browser E2E, responsive viewports, keyboard/accessibility semantics, privacy negatives, and console/hydration review.

## Deferred

Operator dashboard, Booking history, aircraft management, scheduling/crew/manifest, cancellations/refunds, payments/payouts, realtime/notifications, Phase 9.7.B+, Phase 9.8, and Grok visual work remain explicitly deferred.
