# ADR-038: RBAC + resource-scope authorization policy layer

## Status

Accepted

## Context

Role-based access control alone is insufficient: two users may both hold the
`CUSTOMER_OWNER` role, but one must not read the other's trips. Authorization must
combine *who*, *what capability*, and *which tenant's resource*. Scattering string
role checks across routers would be unauditable and error-prone.

## Decision

A single policy layer (`iam/authz.py`) makes every decision as
`authorize(principal, permission, scope)`:

- **Principal** — the authenticated user plus their active memberships (each with
  organization type and tenant links) and status. A non-`ACTIVE` principal is never
  authorized.
- **Permission** — a stable capability vocabulary (`Permission` enum). Roles map to
  permission sets via a single, testable matrix (`ROLE_PERMISSIONS`). Callers ask for
  a permission, never a role name.
- **ResourceScope** — `GLOBAL` (platform-level, no tenant), `CUSTOMER(id)`, or
  `OPERATOR(id)`. A grant is allowed when a membership that grants the permission is
  a `PLATFORM` org (cross-tenant for that permission) **or** a `CUSTOMER`/`OPERATOR`
  membership whose linked tenant id matches the scope.

Default role profiles are deliberately small to avoid role explosion:
`CUSTOMER_OWNER`/`CUSTOMER_ASSISTANT`; `OPERATOR_ADMIN`/`SALES`/`OPERATIONS`/
`FINANCE`/`COMPLIANCE`; `PLATFORM_ADMIN`/`COMPLIANCE_REVIEWER`/`FINANCE_REVIEWER`/
`SUPPORT`; and `PRODUCT_OWNER`.

`PRODUCT_OWNER` is the single high-privilege role holding every permission — a
documented, audited, testable superset, **not** a bypass scattered through the code
(`if email == …`). Role assignment is constrained by organization type, and a
non-platform admin can never grant a role beyond its own permissions (escalation
denied). Denials raise typed errors rendered as safe `401`/`403`; enumeration-
sensitive lookups may mask existence with `404`.

## Consequences

Authorization is centralized, deterministic, and unit-testable in isolation (pure
functions over a `Principal`). New routes declare a permission (+ scope when tenant-
bound); the policy — not the router — decides. Cross-tenant isolation is provable.
