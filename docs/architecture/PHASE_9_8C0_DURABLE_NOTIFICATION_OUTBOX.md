# Phase 9.8.C0 — Durable notification outbox

Canonical base: `329beb58fa6d073fb7c371b555dbb8a1729a002b`. Phase 9.8.C was blocked because
authentication email is synchronous/best-effort and no durable generic outgoing-event
ledger existed. `auth_audit_log`, compliance audit events, incoming provider webhooks, and
financial operations have narrower semantics and cannot serve as a delivery queue.

## Boundary and schema

C0 adds one `notification_outbox` table and no HTTP route. Each row has an opaque UUID plus
a unique trusted `dedupe_key`; fixed machine `event_type`; canonical `recipient_user_id`;
minimal `resource_type`/`resource_id`; and factual delivery, attempt, claim, retry, failure,
and timestamp fields. It stores no email address, rendered subject/body, JSON payload,
passenger data, card data, provider secret, or browser-supplied authority. The recipient FK
uses `RESTRICT`, so account deletion cannot silently erase operational history.

States are `PENDING`, `CLAIMED`, `DELIVERED`, `FAILED_RETRYABLE`, and
`FAILED_PERMANENT`. `DELIVERED` means a future adapter factually accepted delivery.
Retryable work is due only at `next_attempt_at`; permanent failures and delivered rows never
re-enter discovery. Retention remains an owner-policy decision; C0 never deletes rows.

## Transactions, claims, and retries

`create_intent` neither opens nor commits a transaction. Resumed 9.8.C must invoke it inside
the same transaction as the authoritative marketplace transition. The database unique
constraint converges sequential and concurrent replay on one logical record.
Reuse of a dedupe key with incompatible trusted facts fails closed as a programming/domain
collision rather than silently returning the unrelated intent.

Discovery is limited to 1..100. The first audit found that a single mixed-state `OR` query
could scan and top-N sort the entire eligible queue before applying that bound. Discovery now
uses three independently ordered and limited branches: pending rows by `created_at`, due
retryable rows by `next_attempt_at`, and expired claims by `claimed_at`. Their at-most `3 ×
limit` candidates are merged by effective availability, creation time, and UUID, then globally
limited. Thus old retries and expired leases compete factually with pending work instead of
being starved by a fixed state priority.

Each branch is backed by a matching partial PostgreSQL index. A 50,000-row mixed-state
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` regression test compiles and executes the real
repository statement and rejects any sequential outbox scan, missing branch index, or branch
scan beyond the requested bound. The same test suite locks the 1/20/100 limit matrix and exact
due/lease boundaries.

For claims, each bounded branch applies `FOR UPDATE SKIP LOCKED` before the union. This matters
under concurrency: a second worker advances past locks held by the first worker within each
class, rather than observing only an already-locked first page. One `UPDATE ... RETURNING`
still atomically claims the globally selected bounded batch. Multi-row concurrent tests prove
workers obtain disjoint batches with no duplicate ownership.
Claiming explicitly begins a delivery attempt and increments `attempt_count`. Claim token
and timestamp are persisted. An expired lease may be reclaimed with a new token;
compare-and-set completion prevents a stale token from finalizing the newer claim. Future
dispatch policy owns the bounded lease duration and retry-backoff calculation.

The partial indexes are `ix_notification_outbox_pending (created_at, id)`,
`ix_notification_outbox_retry_due (next_attempt_at, created_at, id)`, and
`ix_notification_outbox_claim_expiry (claimed_at, created_at, id)`. Recipient and resource
indexes support bounded operational diagnosis. Queue work reads only outbox rows, so query
count does not grow per recipient.

## Explicit exclusions

C0 adds no email call, template, marketplace event wiring, inbox, HTTP endpoint, dispatcher
daemon, scheduler, dependency, or external-network behavior. Migration `20260828_0011`
descends directly from `20260827_0010`. Resumed 9.8.C must define event-specific recipient
policy, fixed content, verified-address behavior, trusted links, delivery adapter,
lease/backoff constants, and hosted dispatcher ownership before sending notifications.
