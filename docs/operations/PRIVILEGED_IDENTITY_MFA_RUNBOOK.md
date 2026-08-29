# Privileged Identity and MFA Runbook

## Onboard

1. In the correct Auth0 environment, create the named staff identity; require WebAuthn
   or passkey and enrol TOTP as the recovery factor. Do not use SMS/email OTP normally.
2. Create or verify the ACTIVE canonical SBJ user without a shared/default password.
3. Through the trusted bootstrap/admin process, link the verified Auth0 issuer and
   subject to that user. Never link by email.
4. Grant the least-privilege PLATFORM membership.
5. Sign in through **Staff sign in**, prove `amr=mfa`, select the PLATFORM organization,
   and test only the role's allowed actions. Preserve non-secret audit evidence.

Staging and production use different tenants/apps, client IDs, secrets, callbacks and
origins. Never copy a production secret into staging.

## Disable or revoke

Disable the Auth0 identity, revoke all SBJ sessions, and revoke the PLATFORM membership
when appropriate. Local session/membership revocation is immediately authoritative.
Do not delete identity/audit evidence.

## Lost factor or compromise

Pause controlled journeys if the control plane cannot be safely staffed. Disable the
provider identity, revoke SBJ sessions, rotate affected secrets, preserve evidence and
review audit records. Use Auth0's controlled administrator recovery, then re-enrol and
relink only after identity verification. Record explicit resume GO. There is no generic
application break-glass or local-password bypass.

## IdP outage

New staff login is unavailable. Existing MFA-assured sessions survive only within their
bounded local lifetime. Never switch to password auth for platform access. Pause the
external pilot if required roles cannot safely operate.

## Real-provider checklist

Verify exact issuer/audience/signature/nonce/subject, MFA `amr`, PKCE/state replay denial,
JWKS rotation, session expiry, logout, disable/revoke, lost-factor recovery and staging /
production separation. Without this evidence the status is `PROVIDER-BLOCKED`.

