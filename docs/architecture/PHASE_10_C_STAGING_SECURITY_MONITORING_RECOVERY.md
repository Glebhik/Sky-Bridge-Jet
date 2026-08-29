# Phase 10.C — Staging Security, Monitoring and Recovery

## Decision and boundaries

Phase 10.C implements the Phase 10.C0 decision: Auth0 is the primary privileged
identity provider and Clerk is the documented fallback. Customer and operator
accounts remain on Sky Bridge Jet local authentication. Platform staff use a
separate OIDC Authorization Code + PKCE flow and a normal opaque SBJ session.
No live Stripe, production email, refund, payout, or customer/operator migration is
part of this phase.

## Privileged identity

`PrivilegedIdentityProvider` returns only a normalized `VerifiedIdentityAssertion`.
The Auth0 adapter validates the signed ID token, RS256 algorithm, exact issuer,
client-ID audience, expiry, subject, nonce and signed `amr` containing `mfa`. JWKS are
cached by the standards library and refreshed on key-id rotation. Authorization code,
ID/access token, state, nonce, PKCE verifier and client secret are never logged.

OIDC state is server-side, hashed for lookup, ten-minute bounded and one-time. The
nonce and PKCE verifier exist only in the bounded transaction row and are overwritten
when consumed. Provider exchange occurs after transaction consumption and outside a
database transaction. Return paths are fixed server-side.

`external_identity_links` is the immutable trusted mapping. `(issuer, subject)` and
`(provider, user_id)` are unique. Email is display data, never a link key. Linking is
available only as a trusted service/bootstrap seam; there is no public self-link or
automatic user creation.

## Sessions and authorization

The SBJ session stores provider/link references, provider auth time, MFA time,
assurance expiry and optional provider session reference—never an external token or
factor secret. Defaults are 30-minute inactivity, eight-hour absolute session and
eight-hour MFA assurance. Every `/api/v1/platform/**` request passes the universal
assurance gate before existing active-PLATFORM-organization and role authorization.
MFA grants no permission. Local-password-only, expired assurance, disabled user,
revoked membership, revoked session and wrong active organization all fail closed.
The Web platform layout independently revalidates `/auth/me` server-side and requires
the same assurance marker.

Local revocation is immediate. Auth0 disable-to-local-session invalidation is bounded
by local session lifetime until a future back-channel design is approved.

## Environment and staging safety

The explicit environments are development, test, staging and production. FAKE
privileged identity is possible only in development/test and accepts only a
server-configured deterministic code. Staging/production require complete Auth0
configuration and HTTPS callback. Staging rejects live Stripe keys. Staging and
production must use distinct Auth0 tenant/application identity, client IDs, secrets,
origins and databases. Secrets are server-only.

Staging means persistent isolated database, stable HTTPS origin, synthetic data,
invite-only `CONTROLLED_EXTERNAL`, test/fake payments and **NO REAL MONEY**. Edge/WAF
restriction is an infrastructure responsibility; an obscure URL is not access control.

## Readiness, monitoring and recovery

`/health` remains process liveness and makes no external call. `/ready` requires DB
connectivity and exact Alembic revision `20260831_0014`; it never calls Auth0. Provider-
neutral monitoring must consume bounded SQL aggregates for readiness/5xx, aged UNKNOWN
payments, outbox states/age, compliance queue age and pilot mode/participant counts.
No PII or high-cardinality resource labels are allowed. External alert routing remains
provider-blocked; thresholds are configurable rehearsal defaults, not SLAs.

The local backup/restore helper accepts only localhost databases carrying the explicit
`phase10c_rehearsal_` marker and task-scoped `/tmp` artifacts. It refuses overwrite and
cannot target production. Managed PostgreSQL/PITR remains infrastructure-blocked.

## Security headers

Web responses set CSP, DENY framing, nosniff, strict referrer policy and a restrictive
Permissions-Policy. HSTS is emitted only for staging/production. The redirect-based
Auth0 flow needs no wildcard CSP origin. A future embedded provider surface requires a
new reviewed exact origin.

## Provider evidence

Repository-controlled implementation uses the deterministic provider seam. Real Auth0
staging tenant configuration, WebAuthn/TOTP enrolment, signed `amr=mfa`, logout and
lost-factor rehearsal are mandatory before Pilot B identity GO and are truthfully
`PROVIDER-BLOCKED` until credentials and owner authorization exist.

## Independent-audit security repair

The pre-commit independent audit identified a MAJOR test-coverage gap: durable tests
exercised the FAKE seam but did not attack the real Auth0 adapter. The targeted repair
adds deterministic test-only RSA/JWK material and a real signed-token matrix covering
signature and algorithm rejection, exact issuer/audience/nonce/time/subject handling,
literal well-formed `amr=["mfa"]`, unknown-key refresh and rotation, malformed JWKS and
normalized JWKS/provider failure. Private keys and tokens remain runtime-only test
fixtures and never enter production source or logs.

The same durable suite proves callback transaction consumption and replay denial,
expired state, wrong nonce, unlinked/colliding identity, disabled user, missing or
revoked PLATFORM membership, wrong organization kind and new-session issuance. It
derives every `/api/v1/platform/**` operation from the live OpenAPI route graph and
proves both local-password-only and expired-assurance sessions are rejected before
business logic. The adversarial tests exposed and corrected two narrow production
defects: malformed mixed-type `amr` was accepted when it contained `"mfa"`, and PyJWT
JWKS lookup/set failures were not normalized to the safe provider error boundary.
