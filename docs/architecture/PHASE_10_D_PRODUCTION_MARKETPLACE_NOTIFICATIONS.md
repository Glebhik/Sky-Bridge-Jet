# Phase 10.D — Production marketplace notifications

Phase 10.D retains the C0/C closed four-event outbox and selects **Resend**, already used by
the repository's auth-email boundary. The marketplace adapter uses one explicit HTTPS POST,
plain text, fixed server templates/routes, a server-owned From/Reply-To, bounded timeout, and
the notification UUID as Resend's 24-hour idempotency key. No browser send, retry, recipient,
template, provider-key, or generic notification route exists.

## Truthful delivery model

`notification_outbox.delivery_state=DELIVERED` remains the historical dispatcher terminal
meaning: Resend accepted the request. It does **not** mean inbox delivery. Migration
`20260901_0015` adds the opaque `provider_message_id`, normalized provider delivery fact and
event time, plus a minimal provider-event dedupe ledger. Verified `email.delivered`, bounced,
complained, suppressed, delayed, sent and failed webhooks refine that fact without changing
Booking, Offer, TripRequest, Payment or any other business lifecycle. Raw payloads, addresses,
subjects and provider responses are not stored.

The exact `/api/v1/webhooks/resend` route verifies the Svix message id, timestamp and HMAC
signature over the raw bounded body. Five-minute replay age, event-id uniqueness, indexed exact
message correlation and deterministic provider-time ordering close replay, cross-message and
out-of-order races. The projection chooses the latest provider `created_at`; equal instants use
closed semantic severity. Thus an older event cannot falsify a newer timestamp, while a later
bounce/complaint still escalates. Every verified event remains in the minimal ledger, including
older high-risk facts not selected for the latest projection. Unknown messages/events return no
resource oracle. Pre-link events are reconciled by the same ordering when acceptance attaches
the provider message ID.

## Dispatcher

`python -m sky_bridge_jet.modules.notifications.worker` is a small long-running process;
`--once` supports a scheduler. Each run claims 1..100 rows using the existing SKIP LOCKED,
claim-token and ten-minute lease contract, closes DB transactions before network I/O, resolves
recipients/resources in fixed batched queries, and finalizes each row independently. Current
retry policy remains 5 minutes, 30 minutes, then permanent. A provider auth/config/429/5xx
systemic result stops further provider calls in that batch and returns every affected claim to
the bounded 30-minute retry cadence without consuming it into recipient-level permanent
failure; it never mass-classifies recipients as invalid. Non-systemic recipient/transport
failures retain the normal 5-minute, 30-minute, then permanent policy.

Resend HTTP 409 is classified from a bounded minimal error envelope. A
`concurrent_idempotent_requests` conflict is systemic/transient; an
`invalid_idempotent_request`, malformed envelope, or unknown 409 is systemic policy failure.
None is misrepresented as an invalid recipient, and raw provider bodies are neither logged nor
persisted.
Only an explicit recipient-specific provider code is recipient-permanent; generic validation or
sender-configuration errors remain systemic so an ambiguous response cannot burn a recipient.
Resend's current public error catalog does not define a distinct send-time
`invalid_recipient` code: malformed recipient input is therefore rejected by canonical local
validation or treated as systemic when Resend returns generic `validation_error`; later bounce or
suppression is retained as a verified webhook fact. The explicit recipient-specific adapter branch
is a defensive normalized boundary, not a claim about a currently documented Resend error code.

Resend idempotency materially narrows the accepted/local-crash ambiguity but expires after 24
hours. The system therefore promises one durable logical intent and at-least-once bounded
external attempts—not exactly-once inbox delivery. Lifecycle and current verified-recipient
authority are revalidated on every attempt.

## Environment and privacy

Delivery is disabled by default. A disabled worker exits before claiming: it does not increment
attempts, acquire leases, simulate FAKE success, or alter provider/business facts. Resume uses
the same durable queue. Development/test may explicitly enable FAKE. Staging/production enabled
delivery requires Resend; staging additionally requires an exact lowercase recipient allowlist
and prefixes subjects with `[STAGING]`. Production uses only the current canonical verified
email. Templates contain no passenger PII, itinerary detail, financial amount or provider data.
Links derive only from validated `WEB_PUBLIC_ORIGIN` plus fixed routes.

Queue age, retryable/permanent counts and expired leases reuse Phase 10.C diagnostics. Worker
logs contain counts and normalized codes, not addresses or content. A permanent failure in any
of the four critical events requires operations/support manual fallback; delivery failure never
mutates business state. Pilot PAUSED does not discard already-required notifications.

External gates remain: Resend account/projects and secrets, verified sending domain, SPF/DKIM/
DMARC, real staging delivery, bounce/complaint rehearsal, worker host and external alert routing.
No repository result claims these configured.

Explicitly excluded: SMS, WhatsApp, push, marketing, inbox, CRM, payment/refund/payout work,
Terms/Privacy, customer/operator Auth0 migration, and flight operations expansion.

## Independent-audit remediation

The first independent audit found three MAJOR defects: disabled delivery consumed rows through
FAKE success, every Resend 409 became permanent recipient failure, and rank-only webhook updates
could regress provider time. The repairs above are locked by durable disabled/resume/mixed-backlog,
bounded 409, signed temporal webhook, pre-link, and concurrent ordering tests. The audit history
is retained here rather than rewritten as if the defects never existed.
