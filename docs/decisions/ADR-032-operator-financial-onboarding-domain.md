# ADR-032: Operator financial onboarding as a distinct domain from aviation compliance

## Status

Accepted — KYC/KYB/AML/sanctions determinations remain the payment provider's
responsibility (specialist-review gate)

## Context

An operator that is admitted to the aviation marketplace (Phase 6) is not
necessarily able to receive money through the PSP, and vice versa. These are two
different questions answered by two different authorities: Sky Bridge Jet's
compliance reviewers (aviation) and the payment provider (financial identity /
capability). Conflating them would let a financial state silently change an
aviation decision, or fabricate a financial capability the provider never granted.

## Decision

Financial onboarding is a **separate bounded context** (`modules/financials`) with
its own aggregate `OperatorConnectedAccount` and its own provider-neutral lifecycle
status — `NOT_STARTED`, `ONBOARDING_PENDING`, `REQUIREMENTS_DUE`, `UNDER_REVIEW`,
`ENABLED`, `RESTRICTED`, `DISABLED` — **derived** from the provider's reported
capability snapshot (charges/payouts enabled, requirements due, disabled reason),
never mirroring a Stripe internal string one-for-one. It never reads or mutates
Phase 6 aviation compliance state.

Sky Bridge Jet runs **no** independent KYC/KYB/AML/PEP/sanctions engine and stores
**no** bank account, identity document, or beneficial-owner data. Onboarding is
hosted by the provider; the connected-account reference is an **identifier, not a
secret**. Existing operators get no connected account and are therefore
financially `NOT_STARTED` — no auto-approval, no fabricated provider reference.

A separate, explainable `OperatorFinancialEligibility` decision (eligible + typed
reasons) is computed from the stored snapshot. Sky Bridge Jet's Phase 7 policy is
that only `ENABLED` (charges **and** payouts) is eligible; this is a configured
platform policy, not a legal or provider guarantee.

## Consequences

Aviation and financial admission evolve independently and can disagree (financially
enabled yet aviation-suspended, or the reverse) without corrupting each other. The
provider remains the authority for financial identity checks; the platform records
provider-reported state only. A future provider is swapped behind the same
provider-neutral onboarding port.
