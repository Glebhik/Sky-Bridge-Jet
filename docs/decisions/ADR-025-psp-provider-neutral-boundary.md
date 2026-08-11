# ADR-025: PSP / provider-neutral boundary and Merchant-of-Record deferral

## Status

Accepted — commercial/legal/payments classification deferred to specialist review

## Context

Sky Bridge Jet intends to handle payment funds through a licensed payment service
provider / marketplace payment platform rather than by implementing custody, money
transmission, or an internal wallet. The Merchant-of-Record, charge model,
statement descriptor, and dispute-liability allocation depend on legal
contracting, PSP configuration, jurisdiction, and payment method, and are not
resolved.

## Decision

The payment domain talks only to a provider-neutral `PaymentProvider` port with
capabilities `authorize`, `capture`, `void`, and `refund` returning typed,
provider-neutral results; raw provider exceptions never cross the adapter
boundary. Phase 5 ships only a deterministic `FakePaymentProvider` (no real money,
no external calls, unmistakably non-production) selected behind
`get_payment_provider`. No Merchant-of-Record, charge type, PSP account model,
statement descriptor, or webhook-signature security is hard-coded. Provider event
ingestion (webhooks) is documented as a future boundary rather than built as
architecture theatre while there is no real PSP.

## Consequences

A future licensed-PSP adapter, and the Merchant-of-Record / charge-model / payout
configuration, can be introduced behind this port without rewriting the payment
domain. These classifications are explicit specialist-review gates (see the Phase
5 architecture document); the software does not assert they are solved.
