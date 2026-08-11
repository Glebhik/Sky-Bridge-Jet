# ADR-021: Authorization-before-confirmation, capture-after-confirmation

## Status

Accepted

## Context

The approved default flow authorizes a customer's payment before the operator
confirms the booking, and captures only after confirmation. Capture against an
unconfirmed, rejected, or cancelled booking must be impossible, including under
concurrency.

## Decision

A payment may be created and **authorized** while its booking is
`PENDING_OPERATOR_CONFIRMATION` or `CONFIRMED`. **Capture requires the booking to
be `CONFIRMED`**, checked while holding a `SELECT ... FOR UPDATE` row lock on the
booking so a concurrent Phase 4 cancellation cannot interleave. Financial success
is recorded from the provider result and never inferred from booking state.
Provider/payment-method capture capability is explicit and no authorization
validity period is invented; a real adapter reports it.

## Consequences

The critical safety property holds: capture cannot succeed against a
non-confirmed booking, and a capture-vs-cancel race resolves to either a capture
that completed while confirmed or a blocked capture — never a capture after
cancellation. If the booking is rejected or cancelled after authorization, the
authorization is released by an explicit **void**, which is a distinct financial
event from a post-capture refund.
