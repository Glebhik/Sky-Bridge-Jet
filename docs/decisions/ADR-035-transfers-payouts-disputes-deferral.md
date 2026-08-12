# ADR-035: Deferral of transfers, payouts, disputes, tax/VAT, MoR, and PSD2 to specialist review

## Status

Accepted — explicit specialist-review gates, not solved problems

## Context

Connecting a real PSP invites the assumption that fund movement, settlement, tax,
and regulatory obligations are now "handled." They are not, and pretending
otherwise in software would be misleading. Phase 7 keeps the Phase 5 commercial
allocation authoritative and moves no real money.

## Decision

The following are **deliberately not implemented** in Phase 7 and are documented as
specialist-review gates:

- **Transfers and payouts are deferred.** There is no payout scheduler or cron, and
  a provider transfer/payout is **not** a core source of truth. The Phase 5
  operator/platform allocation (ADR-023) remains authoritative. The payment flow
  used for exploration (separate charge and transfer) is a **candidate**, not the
  final legal money-movement design.
- **Merchant-of-Record, charge model, statement descriptor** remain unresolved
  (ADR-025).
- **Disputes/chargebacks** are not adjudicated; a dispute-related event is recorded
  as evidence only and never mutates money totals automatically.
- **Tax / VAT / invoicing** are not computed or asserted.
- **PSD2 / SCA legal applicability** is not determined by the software; the platform
  only represents the provider-reported requirement (ADR-034).
- **KYC/KYB/AML/PEP/sanctions** determinations belong to the provider (ADR-032).

The commercial separation from Phase 5 is preserved end-to-end: operator amount,
platform fee, tax, customer total, captured, and refunded remain distinct. Capture
is never treated as "operator paid," and customer total is never treated as
"platform revenue."

## Consequences

Each deferred concern can be designed and contracted with the appropriate legal,
tax, and payments specialists behind the existing provider-neutral boundaries
without rework of the domain. The software's guarantees stay honest: it records
provider-reported state and enforces platform policy, and it does not claim to have
solved money transmission, taxation, or regulatory classification.
