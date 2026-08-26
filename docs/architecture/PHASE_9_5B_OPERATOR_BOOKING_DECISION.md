# Phase 9.5.B — minimal operator Booking decision

Canonical base: `176ea123674047d63dacb33bac98f36867a4f177`.

## Scope and authority

This slice adds the smallest authenticated operator surface needed to discover and decide
pending Bookings. `GET /api/v1/me/operator-bookings` resolves the authoritative operator from
the principal's active `OPERATOR` organization, requires `booking.read`, filters
`Booking.operator_id` and `PENDING_OPERATOR_CONFIRMATION` in SQL before materialization, orders
by `(created_at, id)`, and bounds `limit` to 1–100. One bounded Booking query plus one batched
leg/airport query avoids N+1 access.

The purpose-built `OperatorBookingView` contains only Booking reference/status, trip and selected
offer references, the operator's commercial amount/currency and legal-name snapshot, aircraft
snapshot, operational route/departure/passenger count, and creation time. It structurally omits
customer identifiers and contact/profile data, passenger identities, customer notes and special
assistance, platform fee, customer total/tax, payment/provider data, decision notes/references,
and audit metadata.

## Decision contract

The existing confirm/reject transaction, Booking row lock, transition validation, selected-offer
authority check, and confirm-time compliance revalidation remain authoritative. The legacy
`operator_id` body member is backward-compatible optional. For ordinary operator users the server
derives the operator from the validated active organization; a supplied value may only confirm
that identity and a mismatch fails closed. The browser never sends or discovers `operator_id`.

`OPERATOR_ADMIN` and `OPERATOR_OPERATIONS` can decide; `OPERATOR_SALES` can read according to its
established `booking.read` permission but receives a factual read-only presentation with no
confirm/reject controls. The API remains the final authorization authority. Cross-operator resource
access remains concealed as 404. Confirm and reject return the existing authoritative response.
A successful item leaves the pending-only queue. A 409 is never retried automatically; the client
refreshes the queue and displays a safe message without compliance internals.

## Web boundary

`/operator/bookings` has a separate server-validated operator boundary and does not reuse the
customer `PortalShell`. Customer-only users receive an operator-access error; anonymous users are
redirected to login. A single operator membership may resolve automatically. Multiple operator
memberships begin with no active operator: the browser issues no queue request and exposes no
decision controls until the user explicitly selects an organization. Switching clears the prior
queue and ignores stale responses. Every queue or decision request carries the selected
organization UUID as request context (the UUID is not exposed as chooser copy), which the API
revalidates.

The same-origin proxy adds exactly `GET me/operator-bookings` and canonical-UUID
`POST bookings/:uuid/confirm|reject`. Segment counts and methods are exact. Booking detail,
cancel/payment, adjacent operator/admin APIs, offer/aircraft/admission mutations, traversal,
encoded separators, malformed UUIDs and extra segments stay closed.

The queue renders loading, error, empty and factual pending states. Review is an explicit decision
step. A synchronous ref plus disabled controls and `aria-busy` permits only one confirm/reject
command per interaction. Results are authoritative; there is no optimistic final state, polling,
payment, Stripe, ticketing claim, customer PII, invented urgency or ranking.

## Persistence and deferred work

There is no model or migration change: Alembic remains `20260813_0009` and no `0010` exists.
The intentional route delta is exactly one operation: `85 / 81 / 4` becomes
`86 registered / 82 OpenAPI / 4 documentation`; route policy classifies the new queue.
Customer reads already expose authoritative `CONFIRMED`/`REJECTED` Booking status while omitting
operator decision notes and references. Payment creation/capture/refund, the broader operator
portal, offer/fleet/compliance administration, polling/freshness (Phase 9.5.C), and Phase 9.6 are
explicitly deferred.

## Implementation and self-verification evidence

A new disposable PostgreSQL lifecycle created two scenarios through customer registration,
development verification, login, passenger creation, TripRequest creation/submission, published
Offer selection and customer Booking creation. Both began `TripRequest=SUBMITTED`,
`Offer=SELECTED`, `Booking=PENDING_OPERATOR_CONFIRMATION`, `Payment=0`. A real operator browser
session discovered both via the queue, confirmed one and rejected the other with
`AIRCRAFT_UNAVAILABLE`; each produced exactly one decision POST with no `operator_id`. The customer
then revisited `/portal/bookings` and saw authoritative CONFIRMED and REJECTED text without operator
notes or identifiers. Scoped SQL proved one Booking per trip, retained SUBMITTED/SELECTED states,
matching operator ownership, and zero Payments.

This evidence was produced during implementation/self-verification; it is not a claim that the
independent audit has been rerun after remediation. The full PostgreSQL suite (505 tests before
remediation) covers cross-operator concealment, customer denial,
read-only role denial, duplicate decisions, confirm/reject concurrency and compliance
revalidation. Web proxy/client/component coverage totalled 299 tests in 33 files before remediation.
Implementation-time runtime checks at
320×568, 390×844, 768×1024, 1024×768 and 1440×900 found no horizontal overflow; semantic headings,
native controls, labelled rejection fieldset/select, textual states, visible focus, disabled
pending controls and `aria-busy` provide the accessibility baseline. Phase 9.5.C freshness,
Phase 9.6 payment work, Phase 9.7 broader operator portal work, and Grok remain deferred.

Remediation self-verification added explicit multi-organization, single-organization, role-aware
decision-control, stale-response, double-reject, mixed-action guard, same-tenant ordering and
pagination coverage. The resulting local gates pass with 506 PostgreSQL-backed API tests and 306
Web tests in 33 files. These are self-verification results awaiting a new independent audit.
