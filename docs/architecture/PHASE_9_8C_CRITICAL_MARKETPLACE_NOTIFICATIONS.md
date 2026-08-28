# Phase 9.8.C — Critical Marketplace Notifications

## Scope and foundation

Phase 9.8.C is based on canonical main `8b5b4dd9b1146665f15e2452fb5cb4274a4186d4`
and reuses the Phase 9.8.C0 `notification_outbox` at Alembic head
`20260828_0011`. C0 remains responsible for database dedupe, bounded eligible
discovery, PostgreSQL claims, claim tokens, lease recovery, attempts, and factual
delivery transitions. Phase C adds no schema, route, Web code, dependency, inbox,
scheduler, or generic email endpoint.

The event catalog is intentionally limited to:

| Event | Authoritative transition | Recipients | Fixed destination |
| --- | --- | --- | --- |
| `OFFER_AVAILABLE` | Offer `DRAFT -> SUBMITTED` | Active, verified customer organization owners and assistants with `booking.read` | `/portal/trip-requests` |
| `BOOKING_PENDING_OPERATOR_CONFIRMATION` | Canonical Booking creation | Active, verified owning-operator admins and operations members with `booking.decide` | `/operator/bookings` |
| `BOOKING_CONFIRMED` | Booking `PENDING_OPERATOR_CONFIRMATION -> CONFIRMED` | Active, verified customer organization owners and assistants with `booking.read` | `/portal/bookings` |
| `BOOKING_REJECTED` | Booking `PENDING_OPERATOR_CONFIRMATION -> REJECTED` | Active, verified customer organization owners and assistants with `booking.read` | `/portal/bookings` |

Opportunity broadcasts are deferred because no bounded subscription or targeting
relationship exists. Payment-exception and compliance email alerts are deferred
because Phases 9.8.B and 9.8.A already provide bounded operational queues. A
general in-app inbox and notification preferences are deferred. FlightOperation
and all Phase 9.8.D concerns remain out of scope.

## Recipient and dedupe policy

Recipients are derived only from canonical resource ownership, organization
membership, role permissions, active user status, and verified email state. No
browser active organization, request recipient, or request email participates.
Each authorized member receives a distinct intent. Recipient selection is capped
at 100; exceeding the cap raises `RecipientFanoutError`, rolling back the business
transaction instead of silently truncating a required recipient set.

The deterministic identity is
`<event>:<authoritative resource UUID>:<recipient user UUID>`. The relevant
transitions are terminal/single-occurrence under the current lifecycle, so the
resource identity is also the authoritative transition identity. C0's unique
dedupe constraint is final authority across replay and process restart. Different
events and recipients cannot collide.

Only active, email-verified users are selected at creation. Email is deliberately
not snapshotted: the dispatcher resolves the current canonical address and active,
verified status. It also rechecks the relevant customer or operator membership and
role against the resource at delivery. A changed verified address receives the
message; an inactive/unverified user or revoked/wrong-tenant membership becomes a
permanent `RECIPIENT_INELIGIBLE` failure without a send.

## Atomicity and payment interaction

The Offer submit, Booking create, Booking confirm, and Booking reject services
create every required intent in their existing explicit business transaction.
The C0 creation primitive is transaction-neutral. A business failure, outbox
failure, or failure after the first of several recipient inserts rolls back both
the mutation and every intent. Business services never invoke a sender,
dispatcher, Resend, SMTP, or network operation.

Booking confirmation/rejection preserves the established Phase 9.6 orchestration:
the notification states only the committed Booking fact and makes no claim about
capture, void, refund, settlement, or other financial outcome. A provider failure
that prevents a Booking transition from committing produces no lifecycle intent.
Post-commit delivery failure never changes Booking, Offer, TripRequest, Payment,
PaymentOperation, Aircraft, compliance, or financial amounts.

## Templates, links, and privacy

Templates are a closed server-owned mapping. The delivery adapter receives only a
canonical current email plus a fixed subject and text body. Bodies are minimal:

- an offer is available for review;
- a booking awaits operator review;
- a booking is confirmed; or
- a booking was not confirmed and current status can be reviewed.

They do not imply offer acceptance, aircraft guarantee, flight completion,
regulatory approval, capture, void, refund, settlement, or operator fault. They
contain no customer/passenger identity, itinerary, notes, DOB, passport,
nationality, medical data, pricing decomposition, payment/provider data, secrets,
or credentials. Links concatenate a fixed safe route with the trusted server-side
`web_public_origin`; they contain no identifiers, email, tokens, or sensitive query
parameters. Resource lookup is used only for authorization and is batched by event
class, not to render content.

## Delivery and failure model

`MarketplaceNotificationSender` is a provider-neutral protocol. The deterministic
FAKE adapter records attempts and accepted messages and supports success,
transient failure, permanent failure, and accepted-but-response-unknown modes.
There is deliberately no production Resend/SMTP adapter activation in this phase;
the existing auth-email sender, configuration, and Resend behavior are unchanged.
Provider activation is separate operational work and must remain fail closed.

`MarketplaceNotificationDispatcher` is a direct internal service seam for a future
hosted management/scheduler invocation. It has no HTTP route or background daemon.
One call claims one C0-ordered batch with a caller limit of 1..100. The fixed lease
is 10 minutes. Recipient users are loaded in one bounded query and authorization
resources in at most one additional query per present event/resource class, so
query growth is fixed by the four-class catalog rather than notification count.
Templates require no per-row resource query.

### Delivery-time lifecycle applicability

The independent audit found that the original dispatcher rechecked tenant and
membership authority but could still send present-tense copy after the resource had
advanced. In particular, a withdrawn Offer was described as available and a
confirmed Booking was described as awaiting operator confirmation. The repaired
dispatcher therefore treats every template as a **current-state notification** and
revalidates applicability after claim and immediately before render/send:

| Event | Required canonical state at delivery |
| --- | --- |
| `OFFER_AVAILABLE` | `effective_offer_status(...) == SUBMITTED` |
| `BOOKING_PENDING_OPERATOR_CONFIRMATION` | `PENDING_OPERATOR_CONFIRMATION` |
| `BOOKING_CONFIRMED` | `CONFIRMED` |
| `BOOKING_REJECTED` | `REJECTED` |

The canonical Offer helper derives `EXPIRED`; persisted `DRAFT`, `WITHDRAWN`, and
`SELECTED`, and derived `EXPIRED`, are all inapplicable. A confirmed intent becomes
inapplicable after cancellation. Rejected is currently terminal. Missing resources,
unknown events, unknown states, and mismatched resource types fail closed.

Recipient/account/membership eligibility is evaluated before applicability for a
normal existing resource. If both authorization and lifecycle are invalid, the
recipient failure deterministically wins; either outcome is permanent and sends
nothing. An applicable-row transient failure is revalidated on every later claim,
so a lifecycle change before retry suppresses the stale send. The dispatcher never
synthesizes a replacement event; authoritative business transitions create their
own intents.

Stale claimed work retains the factual C0 attempt increment and becomes
`FAILED_PERMANENT` with bounded code `EVENT_NO_LONGER_APPLICABLE`. It is neither
deleted nor marked delivered and cannot re-enter the due queue. Existing outbox
fields provide its operational history without a migration or UI.

Offer IDs and Booking IDs are loaded in at most one bounded query per resource
class for up to 100 claimed notifications. This is additional to the fixed batched
recipient/authorization queries and introduces no per-notification lookup. These
reads and the outbox claim transaction close before adapter invocation; no Offer or
Booking lock, and no business transaction, is held across external delivery.

There is an unavoidable narrow external race after the final applicability read:
if a concurrent business transition commits only after a provider invocation has
begun, the already-started email cannot be recalled. The repair guarantees that a
state change committed before applicability evaluation suppresses delivery. It does
not hold business locks across network I/O or claim stronger email synchronization.

The retry policy is deterministic and server-owned: attempt 1 retries after five
minutes, attempt 2 after thirty minutes, and a retryable failure on attempt 3
becomes permanent. The same row, dedupe key, and notification ID are always used.
Permanent failures are not redispatched. Persisted failure codes are normalized:
`TRANSIENT_PROVIDER`, `INVALID_RECIPIENT`, `RECIPIENT_INELIGIBLE`,
`EVENT_NO_LONGER_APPLICABLE`, `TEMPLATE_ERROR`, or `UNKNOWN_DELIVERY_RESULT`; raw
provider responses are never stored.

Success is marked `DELIVERED` only after sender acknowledgement. If a provider may
have accepted a message but the response is unknown, the row becomes retryable and
is never fabricated as delivered. A later retry may therefore duplicate an
external email. The guarantee is exactly one logical notification intent with
bounded retries and factual internal state, **not exactly-once external email
delivery**.

C0 atomic claims prevent simultaneous row ownership. A fresh process/session can
recover pending or retryable work. An expired claim can be reclaimed after the
10-minute lease, and every late success or failure from the old worker is rejected
by claim-token comparison. Unknown catalog events and resource-type mismatches fail
closed without sending.

## Observability and operations

C0 already stores event, recipient user, resource, state, attempt count, claim and
delivery timestamps, next attempt, and normalized failure code. Its bounded,
deterministically ordered repository discovery is sufficient for Phase C
operational diagnosis of retryable work, permanent failures, and aged claims; no
browser console or new read/mutation surface is justified. Production logs must use
notification/resource/user identifiers and normalized state/code only—never an
email address, rendered body, provider response, or secret.

Deployment follow-up is limited to choosing and securely configuring a production
marketplace email adapter and invoking the bounded dispatcher from hosted
operations. It must not alter the recipient, template, dedupe, claim-token, retry,
privacy, or transaction contracts above. No real provider call was made in Phase
9.8.C implementation or E2E.
