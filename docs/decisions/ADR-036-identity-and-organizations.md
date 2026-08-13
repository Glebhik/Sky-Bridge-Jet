# ADR-036: Human identity and organizations distinct from Customer/Operator aggregates

## Status

Accepted

## Context

Phases 2–7 model commercial entities (`Customer`, `Operator`) and transactions, but
have no concept of an authenticated human or of *who may act on whose behalf*. A
naive design would equate one login with one Customer or one Operator. Reality is
many-to-many: a family office or PA acts for a Customer; multiple staff act for an
Operator; platform staff act across tenants.

## Decision

Introduce a separate identity/access bounded context (`modules/iam`) with three new
aggregates, none of which replace the Phase 2–7 aggregates:

- **`User`** — a human identity with an opaque UUID primary key (email is **not**
  the PK), unique by case-normalized email, minimal PII (no passport/DOB/address),
  and an explicit lifecycle (`PENDING_VERIFICATION` → `ACTIVE` → `SUSPENDED` /
  `DISABLED`). Disabling never deletes security/audit history.
- **`Organization`** — the context a human acts within: `CUSTOMER`, `OPERATOR`, or
  `PLATFORM`. It optionally links **by reference** (nullable one-to-one FK) to an
  existing `customers.id` or `operators.id`, so the aviation/commercial aggregates
  are reused, not rewritten. Resource-scope checks resolve through these links.
- **`OrganizationMembership`** — a user's role within an organization, with at most
  one `ACTIVE` row per (user, organization) enforced by a partial unique index;
  revocation sets `revoked_at`/`REVOKED` rather than deleting (audit retained).

## Consequences

The commercial model and the human-access model evolve independently. A Customer can
be operated by several users; an Operator can have many staff; platform staff exist
without hard-coded emails. Future evolution (teams, sub-orgs) fits behind these types
without touching Phase 2–7. See ADR-037 (auth/session), ADR-038 (authorization),
ADR-039 (API security migration).
