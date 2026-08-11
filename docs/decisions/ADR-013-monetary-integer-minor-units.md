# ADR-013: Monetary amounts as integer minor units

## Status

Accepted

## Context

Phase 3 introduces commercial money on operator offers: an operator amount, a
platform fee, taxes, and a customer total. Floating point cannot represent money
exactly and must never be used. The price components must also be internally
consistent (total equals the sum of its parts) and enforceable by the database.

## Decision

Store every monetary amount as a non-negative integer number of minor units
(for example euro cents) in a `BIGINT` column, paired with an ISO 4217 currency
code. Phase 3 supports EUR, GBP, and USD, which are all minor-unit-scale 2, so a
single integer representation is unambiguous. A single offer uses one currency
and no foreign-exchange conversion is performed.

Integer arithmetic makes the consistency invariant
`total = operator + platform_fee + tax` exact, so it is expressed both in the
domain layer and as a PostgreSQL `CHECK` constraint, alongside non-negativity
checks.

## Consequences

Money is exact and database-enforced. Currencies whose minor unit is not scale 2
(for example JPY) are out of scope until a scale-aware representation is added.
Cross-currency comparison and FX remain deferred. The API exposes amounts as
integer minor units plus the currency, which a future frontend formats.
