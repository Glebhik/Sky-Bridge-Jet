# ADR-044: Customer self-provisioning and invitation precedence (Phase 9.0.B)

## Status

Accepted (Phase 9.0.B). Backend foundation for the future Customer Portal. No frontend,
no schema change, no migration.

## Context

After Phases 9.0.A-1/A-2/A-3 the resource chains are authorization-bound, but a
self-registering individual had no customer tenant, so they could authenticate yet do
nothing. Phase 9.0.B provisions a personal customer tenant automatically and safely.

## Decision

**On successful email verification, a normal self-registering individual is atomically
provisioned a personal customer tenant:** one `Customer`, one CUSTOMER `Organization`
linked to it (canonical `customer_id`), and one active `CUSTOMER_OWNER`
`OrganizationMembership`. The client supplies no identifiers, role, or organization type
— everything is server-controlled. `POST /api/v1/customers` remains platform-admin only;
no new public arbitrary-customer endpoint is added.

**Atomicity.** Provisioning runs **inside the existing email-verification transaction**
(`AuthService.verify_email`), which already opens one `session.begin()` and locks the
user row (`get_for_update`). Verification (token consumption + activation), the three
tenant records, and the audit record therefore commit together or roll back together —
no partial data, no misleading success. If provisioning fails, verification fails with
it.

**Idempotency / concurrency.** The verification token is single-use (`consumed_at`), and
the user row-lock serializes concurrent verifications, so concurrent or repeated
verification produces **at most one** Customer, Organization, and owner Membership.
Provisioning additionally skips if the user already has an active membership.

**Precedence (PO decision B).** Provisioning is **skipped** when a higher-precedence path
applies, so an invited operator/platform/family-office user is never given an unintended
personal customer tenant:

- the user is not `ACTIVE` (a suspended/disabled user never provisions);
- the user already has an active organization membership;
- a still-valid **pending invitation** exists for the user's email
  (`OrganizationInvitation` with `PENDING` status and unexpired `expires_at`).

The invitation workflow is unchanged; acceptance remains authoritative.

**Neutral provisional identity (PO decision D).** The `Customer`/`Organization` schema
requires a display name. We use a fixed neutral placeholder, `"Personal account"` — never
a company name and never derived from the email — provisional until the Phase 9.1
customer-profile experience lets the owner set it. The `Customer.primary_email` uses the
user's own verified email (appropriate use of verified user data).

**Audit (ADR-044).** A successful new provisioning writes exactly one append-only
`customer_self_provisioned` record to the Phase 8 `auth_audit_log`, capturing the acting
user and the new organization id only — never a password, verification/invitation/session
token, request body, email address, or PII beyond canonical identifiers. Repeated /
idempotent verification, the invitation path, the existing-membership path, and a failed
provisioning write no event; an audit failure rolls the whole verification back.

## Consequences

A self-registering individual becomes a working customer with a tenant, atomically and
idempotently, without any client-supplied identity. Invited and platform/operator users
are unaffected. The neutral display name and profile editing are deferred to Phase 9.1.
No migration is required — the flow uses existing Phase 8 entities and their constraints.
