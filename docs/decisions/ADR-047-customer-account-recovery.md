# ADR-047: Authenticated customer-account recovery (Phase 9.1.A)

## Status

Accepted (Phase 9.1.A). Adds one authenticated self-service endpoint that reuses the
Phase 9.0.B provisioning path. No new role or permission, no denormalized field, no
migration.

## Context

Phase 9.0.B (ADR-044) provisions a personal customer tenant when a self-registering
individual verifies their email — unless a higher-precedence path applies (the user is not
ACTIVE, already has a membership, or a still-valid pending invitation exists). That leaves a
real gap: a user who had a **valid pending invitation at verification time** (so
self-provisioning was skipped) and whose invitation later **lapsed** (expired or was
revoked) is a "stranded" account — ACTIVE and verified but with no organization, unable to
do anything. Pre-9.0.B verified users are stranded for the same structural reason. The
PR #15 audit required a safe self-service recovery path.

## Decision

**Endpoint.** `POST /api/v1/auth/customer-account/recover` — repository-consistent with the
other `/auth/*` self routes. It is a **non-public POST under the versioned router**, so the
global gate (`enforce_authentication`) already requires an authenticated session and a valid
CSRF token; it is **rate-limited** with the existing `RateLimiter` (5/60s, keyed by the
acting user). The request body is **empty**; the caller supplies no ownership identifiers.
The response is a minimal, safe `AccountRecoveryResponse` — `organization_id`,
`customer_id`, `organization_type` (`CUSTOMER`), and `role` (`CUSTOMER_OWNER`) — with no
audit, membership-internal, or foreign-tenant detail.

**Single provisioning path.** Recovery reuses `provision_personal_customer` (ADR-044) rather
than creating a competing path; that function gained only an `event` parameter so the audit
event differs. `recover_personal_customer` classifies eligibility into safe HTTP outcomes
and then calls it. Identity is always server-derived: the tenant is always one INDIVIDUAL
`Customer`, one CUSTOMER `Organization`, one active `CUSTOMER_OWNER` membership. No
OPERATOR/PLATFORM tenant is ever creatable, and no client value influences ownership.

**Eligibility & denial** (classified under the row lock; see below):

| Condition | Outcome |
| --- | --- |
| No authenticated session (missing/invalid/expired/revoked) | 401 (gate) |
| Locked user not ACTIVE (suspended/disabled/unverified) | 401 at the gate¹; 403 at the service (defense in depth) |
| Active membership already exists | 409 `account_already_provisioned` |
| Valid pending invitation exists | 409 `pending_invitation_exists` |
| Rate limit exceeded | 429 |
| Eligible | 201 + one personal tenant |

¹ A non-ACTIVE user's sessions stop resolving at the authentication gate, so in practice the
request is denied with 401 before the endpoint runs; the service still re-checks the locked
row and raises 403 if somehow reached. Expired and revoked invitations do **not** block
recovery (only PENDING + unexpired counts). Error bodies never disclose the inviting
organization, issuer, or role.

**Transaction, locking, idempotency.** Recovery runs in one transaction and **locks the
canonical user row first** (`get_for_update`). Concurrent or repeated recovery for the same
user therefore serialize on that lock and produce **at most one** tenant — a second caller
sees the now-existing membership and receives 409. Recovery and invitation acceptance cannot
produce conflicting or partial state: recovery is gated on "no valid pending invitation"
under the user lock, and acceptance commits its membership and the invitation's ACCEPTED
status atomically, so recovery reads either {PENDING invitation → 409} or {membership exists
→ 409}. No change to the invitation-acceptance transaction was required. A provisioning or
audit failure rolls the entire transaction back — Customer, Organization, Membership, and
the audit record — leaving no partial tenant.

**Audit.** A successful recovery writes exactly one append-only `customer_account_recovered`
record (acting user id + new organization id only — never a token, password, session/CSRF
value, email, request body, or PII). The verification-time `customer_self_provisioned`
event is unchanged and never rewritten. Denied, rate-limited, replayed, and failed recovery
requests write no success event.

## Consequences

A stranded authenticated user can safely self-provision exactly one personal customer tenant
without any client-supplied identity, idempotently and concurrency-safely, and the audit
trail distinguishes recovery from verification-time provisioning. Invitation precedence and
all Phase 8/9.0 invariants are preserved. The customer portal that surfaces this flow is
Phase 9.1.B.
