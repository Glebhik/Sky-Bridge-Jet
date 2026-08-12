# ADR-027: Compliance evidence and effective-expiration model

## Status

Accepted

## Context

Operators supply evidence of operating authority (AOC), insurance, and aircraft
operating authority. Evidence existing is not the same as evidence being
verified, and verified evidence expires and is renewed. The model must be
provider-neutral (not hard-coded to one jurisdiction's documents), must store no
raw document contents, and must not require a scheduler to expire rows.

## Decision

Use one `compliance_evidence` table with an `evidence_type` discriminator
(`OPERATING_AUTHORITY`, `INSURANCE`, `AIRCRAFT_OPERATING_AUTHORITY`, `OTHER`) and
type-relevant metadata: reference number, issuing authority, jurisdiction,
insurer name, optional `authority_basis`, an opaque `storage_object_reference`
(never the document bytes), and a timezone-aware `effective_date`/`expiry_date`
window (database `CHECK` that expiry ≥ effective). Evidence has a
`SUBMITTED → {UNDER_REVIEW} → VERIFIED | REJECTED`, `→ SUPERSEDED` lifecycle.

**Expiration is effective, not persisted**: verified evidence with an
`expiry_date` in the past reports an effective status of `EXPIRED` and does not
satisfy a compliance gate. Renewal uses supersession — the superseded record and
its review history are preserved, never destructively overwritten.

## Consequences

Evidence review and evidence validity are distinct facts; expired evidence cannot
silently keep an operator eligible; audit history survives renewal; no scheduler
is needed. Whether specific evidence is legally sufficient (coverage amounts,
jurisdictional adequacy) is deliberately out of scope and left to specialist
review.
