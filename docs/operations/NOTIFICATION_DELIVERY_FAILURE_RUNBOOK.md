# Notification delivery failure and manual fallback

- Retryable/429/5xx/timeout: preserve the logical intent and bounded retry schedule. Timeout is
  an unknown result, never false delivery.
- Provider 401/403, sender-domain or quota failure: treat as systemic, stop further calls in the
  batch, alert operations and correct configuration; do not burn recipients permanently.
- Resend `concurrent_idempotent_requests`: systemic transient; retry the same durable intent and
  idempotency key. `invalid_idempotent_request`, unknown 409, or malformed bounded error envelope:
  systemic policy incident; investigate payload/configuration and never label the recipient bad.
- Invalid/ineligible/unverified recipient, hard bounce or suppression: no blind retry. Confirm
  the event remains applicable and start approved manual fallback.
- Treat only an explicit recipient-specific provider code as invalid-recipient. Generic
  `validation_error`, sender-address failures, malformed envelopes, and unknown codes are systemic
  until investigated. Resend's current public error catalog does not publish a distinct
  send-time `invalid_recipient` code; verified bounce/suppression arrives through the webhook
  lifecycle instead.
- Complaint: retain the provider fact and suppression; never disable the SBJ user or mutate a
  Booking automatically.
- Stale event or revoked membership: no send and no manual delivery of obsolete copy.
- Duplicate/unknown webhook: idempotent no-op without exposing whether a message exists.
- Provider facts use provider `created_at`: older arrivals cannot replace a newer projected fact;
  equal timestamps use semantic severity. A later complaint/bounce escalates, while all verified
  events remain available in the minimal ledger for operational evidence.

For any permanently failed critical event, operations/support verifies current lifecycle and
recipient authority, uses the approved backup contact process, records the factual contact in
the controlled external tracker, and escalates serious disruption. Email failure alone never
changes Booking, Offer, TripRequest, Payment, PaymentOperation or FlightOperation. Stop new
controlled journeys when communication safety cannot be maintained.
