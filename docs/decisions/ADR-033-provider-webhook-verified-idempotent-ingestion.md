# ADR-033: Verified, idempotent, data-minimized provider webhook ingestion

## Status

Accepted

## Context

Phase 5 deliberately deferred webhook ingestion (ADR-025). With a real Stripe test
mode, the platform must accept asynchronous provider events (authorization
completion after SCA, capability updates) safely. Webhooks are attacker-reachable,
delivered at-least-once, and can arrive out of order; naive handling risks forged
events, double captures/refunds, or state regressions.

## Decision

The webhook endpoint follows **route → verify → normalize → reconcile → domain**,
not "all logic in the route":

1. **Verify first.** The raw request body is preserved and the signature is
   verified in the gateway using the webhook secret before any parsing. A missing
   or invalid signature is rejected (HTTP 400) with a safe envelope; the endpoint
   is a no-op until Stripe is configured (HTTP 503).
2. **Normalize.** The verified event is converted to a provider-neutral
   `NormalizedProviderEvent`; no raw payload flows further.
3. **Idempotent persistence.** A `provider_webhook_events` row is keyed by a
   database-enforced unique `(payment_provider, provider_event_id)`. Duplicate and
   concurrently-raced deliveries are detected (pre-check plus `IntegrityError`
   handling) and acknowledged as duplicates without re-applying effects.
4. **Only legal domain transitions.** Reconciliation applies a payment event only
   from a valid current state (authorization only from `CREATED`; capture only from
   `AUTHORIZED` **and** a `CONFIRMED` booking), so replayed or out-of-order events
   never double-capture, double-refund, or regress state. The domain refund command
   remains authoritative for amounts; `charge.refunded` is recorded as evidence
   only.

The event record is **data-minimized**: only normalized metadata (provider, event
id, type, processing status, an entity reference, timestamps) is stored — never the
raw event body and never card or secret material.

## Consequences

Event ingestion is safe under forgery, replay, duplication, and reordering, and is
fully testable without Stripe network access by injecting a fake gateway and
overriding the verification context. Reconciliation runs inside the caller's
transaction so a failed dispatch rolls back the event record atomically.
