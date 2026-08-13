# ADR-034: Representing SCA / requires-customer-action without altering the payment status enum

## Status

Accepted — PSD2/SCA legal applicability deferred to specialist review (ADR-035)

## Context

Strong Customer Authentication (e.g. 3-D Secure) means an authorization can enter an
intermediate state where the customer must complete an action off-platform before
the provider finalizes it. The system needs a provider-neutral representation of
this state and must return the client action safely — without exposing secrets and
without a card-only assumption. Adding a value to the existing `payment_status`
PostgreSQL enum would require an effectively irreversible `ALTER TYPE ... ADD VALUE`.

## Decision

The intermediate state is represented **without** changing the `PaymentStatus`
enum. A provider outcome `REQUIRES_ACTION` maps to: the payment **remaining
`CREATED`**, a `requires_customer_action` boolean set true, the normalized
`provider_status` recorded, and the provider reference stored. The authorize
command is recorded in the idempotency ledger so a retry with the same key replays
the pending state rather than creating a second intent. A later **verified webhook**
transitions `CREATED → AUTHORIZED` and clears the flag.

The `ClientAction` (action type + client secret) is returned **once** on the
authorize response as transient, non-persisted data (a `__allow_unmapped__`
attribute on the payment, never a column). The client secret is the provider's
client-SDK material for completing the challenge; it is never stored server-side,
never logged, and does not appear on any read model other than that single authorize
response.

Capture remains gated on a `CONFIRMED` booking (Phase 5, ADR-021): the adapter must
not capture merely because Stripe reports an authorization.

## Consequences

SCA is supported for non-card methods too (the representation is provider-neutral),
with no schema-migration hazard from enum mutation. The client secret's exposure is
bounded to exactly the response that needs it. Whether SCA/PSD2 legally applies to a
given transaction is a specialist-review gate, not a claim the software makes.
