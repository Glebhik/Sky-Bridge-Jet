# ADR-014: Operator price, platform fee, and customer price boundary

## Status

Accepted

## Context

Sky Bridge Jet is a charter intermediary, so an offer's price has three distinct
commercial meanings: the amount the operator charges, the Sky Bridge Jet
commercial fee, and the final price the customer pays. The long-term commission
and pricing model is a business decision that will evolve and must not be baked
into the domain architecture. Phase 3 still needs a fee that can be represented,
stored, and tested today.

## Decision

Model the three amounts as separate persisted fields on each offer:
`operator_amount_minor`, `platform_fee_minor`, and `total_amount_minor` (plus
`tax_amount_minor`). The platform fee is **derived**, not client-supplied: a
single pure policy function, `compute_platform_fee_minor`, computes it from the
operator amount using a default basis-points rate. Offer creation and update
always recompute the fee and total through this function, and the total is
validated for consistency in both the domain and the database.

## Consequences

The operator/platform/customer boundary is explicit and each amount is
independently inspectable. Because the fee lives behind one deterministic
function with a configurable rate, a future commission model (tiered, per-route,
negotiated) can replace it without changing the aggregate, the API shape, or the
persisted schema. This is deliberately not a pricing engine: no dynamic pricing,
discounts, or FX are implied. Clients cannot inject an inconsistent fee because
they never supply it.
